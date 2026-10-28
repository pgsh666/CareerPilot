"""Group/turn compatibility, evidence integrity and fee-free report recovery."""
import json
from copy import deepcopy

import pytest
from sqlalchemy import select
from test_model_budget import gateway, posts, reply
from test_model_budget import model as model
from test_training import read, start, wait
from test_training import training as training
from training_support import FakeGateway

from app.errors import ApiError
from app.model_budget import BudgetGuard
from app.model_validation import diagnostic, rejected_result
from app.models import GenerationJob, ModelSpend, Training, TrainingAnswer, TrainingQuestion
from app.reporting import evidence_spans
from app.scoring import aggregate, snapshot
from app.training_prompts import prepare
from app.training_schemas import QuestionFeedback
from app.training_service import report_input


def sample(count=5):
    rubric = snapshot({"role": "AI 产品经理", "direction": "AI产品"})
    common = [d["id"] for d in rubric["dimensions"][:3]]
    specifics = [d["id"] for d in rubric["dimensions"][3:]]
    data = {"context": {}, "scoring": rubric, "groups": [], "questions": [], "answers": []}
    for main in range(1, count + 1):
        dims = common + [specifics[(main - 1) % 3]]
        data["groups"].append({"id": f"q{main}", "main": main, "dimension_ids": dims, "reference_points": ["说明做法"]})
        for follow in range(3):
            qid = f"q{main}" + (f"f{follow}" if follow else "")
            text = f"第{main}组第{follow}次作答：我先明确目标，再验证结果。"
            data["questions"].append({"id": qid, "main": main, "follow": follow,
                                      "text": "你会怎么验证？", "dimension_ids": dims, "reference_points": ["说明验证方法"]})
            data["answers"].append({"id": "a-" + qid, "question_id": qid, "text": text, "skipped": False})
    return data


def generated(data):
    schema, _, content, validate = prepare("report", data)
    result = FakeGateway().generate(schema=schema, content=content, purpose="report")["output"]
    return result, validate


@pytest.mark.parametrize("count", [3, 5, 8])
def test_wire_groups_all_turns_and_bounds_output_to_actual_main_ids(count):
    data = sample(count)
    schema, prompt, content, validate = prepare("report", data)
    wire = json.loads(content)
    assert "questions" not in wire and "answers" not in wire
    assert len(wire["report_groups"]) == count
    assert all(len(g["turns"]) == 3 for g in wire["report_groups"])
    assert all(sum(len(t["answers"]) for t in g["turns"]) == 3 for g in wire["report_groups"])
    contract = schema.model_json_schema()
    assert contract["properties"]["ratings"]["maxItems"] == count
    assert contract["properties"]["questions"]["minItems"] == count
    assert contract["$defs"]["GroupRating"]["properties"]["question_id"]["enum"] == wire["expected_group_ids"]
    assert contract["$defs"]["DimensionRating"]["properties"]["reason"]["maxLength"] == 40
    assert "不能拆开评分" in prompt and "不自行抄写" in prompt
    assert "report_groups中锁定的dimension_ids" in prompt
    result = FakeGateway().generate(schema=schema, content=content, purpose="report")["output"]
    validate(result)
    assert len(result.ratings) == len(result.questions) == count


def test_root_skipped_but_followup_answered_is_one_group_and_unanswered_stays_out_of_output():
    data = sample(5)
    data["answers"] = [a for a in data["answers"] if a["question_id"] not in {"q1", "q5", "q5f1", "q5f2"}]
    _, _, content, _ = prepare("report", data)
    wire = json.loads(content)
    assert wire["expected_group_ids"] == ["q1", "q2", "q3", "q4"]
    assert wire["report_groups"][0]["turns"][0]["answers"] == []
    assert len(data["groups"]) == 5
    result, validate = generated(data)
    validate(result)
    score = aggregate(data["scoring"], data["groups"], result.model_dump()["ratings"], 4)
    assert score["plannedGroups"] == 5


def test_per_turn_feedback_is_merged_after_every_quote_is_checked():
    data = sample()
    result, validate = generated(data)
    result.questions = [QuestionFeedback(question_id=a["question_id"],
        strengths=[{"answer_id": a["id"], "quote": a["text"], "comment": "说明了做法"}], missing=[])
        for a in data["answers"]]
    validate(result)
    assert [q.question_id for q in result.questions] == ["q1", "q2", "q3", "q4", "q5"]
    assert all(len(q.strengths) == 3 for q in result.questions)


def test_compatible_followup_ids_and_exact_duplicate_ratings_do_not_change_scores():
    data = sample(8)
    result, validate = generated(data)
    before = aggregate(data["scoring"], data["groups"], result.model_dump()["ratings"], 8)
    duplicates = []
    for item in result.ratings:
        for follow in (1, 2):
            duplicate = item.model_copy(deep=True)
            duplicate.question_id += f"f{follow}"
            duplicates.append(duplicate)
        item.question_id += "f1"
    raw = result.model_dump()
    raw["ratings"] += [item.model_dump() for item in duplicates]
    schema, _, _, _ = prepare("report", data)
    result = schema.model_validate(raw, strict=True)
    assert len(result.ratings) == 24  # Compatibility parser; advertised output remains 8.
    validate(result)
    assert len(result.ratings) == 8
    assert aggregate(data["scoring"], data["groups"], result.model_dump()["ratings"], 8) == before


@pytest.mark.parametrize("failure", ["conflict", "fake_duplicate_quote", "wrong_dimension", "cross_feedback", "unknown_group"])
def test_semantic_errors_are_not_hidden_by_grouping_or_deduplication(failure):
    data = sample()
    result, validate = generated(data)
    duplicate = result.ratings[0].model_copy(deep=True)
    duplicate.question_id = "q1f2"
    if failure == "conflict":
        duplicate.dimensions[0].level = 0
        result.ratings.append(duplicate)
        reason = "Conflicting ratings"
    elif failure == "fake_duplicate_quote":
        duplicate.dimensions[0].evidence[0].quote = "这句原话根本不存在"
        result.ratings.append(duplicate)
        reason = "own group"
    elif failure == "wrong_dimension":
        result.ratings[0].dimensions[0].dimension_id = "invented"
        reason = "preassigned dimensions"
    elif failure == "cross_feedback":
        result.questions[0].strengths[0].answer_id = "a-q2"
        reason = "crosses"
    else:
        result.questions[0].question_id = "invented-question"
        reason = "omits or invents"
    before = result.model_dump()
    with pytest.raises(ValueError, match=reason):
        validate(result)
    assert result.model_dump() == before


def test_no_evidence_creates_a_valid_report_without_a_total_score():
    data = sample(3)
    for answer in data["answers"]:
        answer["text"] = "我不知道。"
    result, validate = generated(data)
    validate(result)
    assert all(d.level is None for g in result.ratings for d in g.dimensions)
    assert aggregate(data["scoring"], data["groups"], result.model_dump()["ratings"], 3)["score"] is None


@pytest.mark.parametrize("claimed", ["q1", "q1f1", "q1f2", None])
def test_improvement_uses_authentic_answer_turn_within_the_same_group(claimed):
    data = sample()
    result, validate = generated(data)
    raw = result.model_dump()
    answer = next(a for a in data["answers"] if a["question_id"] == "q1f2")
    raw["improvements"] = [{"answer_id": answer["id"], "quote": answer["text"],
                             "focus": "验证", "suggestion": "说明判断依据"}]
    if claimed:
        raw["improvements"][0]["question_id"] = claimed
    schema, _, _, _ = prepare("report", data)
    parsed = schema.model_validate(raw, strict=True)
    before = deepcopy(raw)
    validate(parsed)
    assert parsed.improvements[0].question_id == "q1f2"
    assert parsed.improvements[0].quote == answer["text"]
    assert raw == before


def test_improvement_cannot_rebind_from_another_known_group():
    data = sample()
    result, validate = generated(data)
    result.improvements[0].question_id = "q2"
    before = result.model_dump()
    with pytest.raises(ValueError, match="crosses"):
        validate(result)
    assert result.model_dump() == before


def referenced_output(data):
    result, _ = generated(data)
    raw = result.model_dump()
    _, spans = evidence_spans(data)

    def convert(item):
        reference = spans[item.pop("answer_id")][0]["id"]
        item.pop("quote")
        item["evidence_ref"] = reference

    for feedback in raw["questions"]:
        for item in feedback["strengths"] + feedback["missing"]:
            convert(item)
    for group in raw["ratings"]:
        for dimension in group["dimensions"]:
            for item in dimension["evidence"]:
                convert(item)
    for item in raw["improvements"]:
        convert(item)
        item.pop("question_id")
    return raw


def test_source_references_resolve_to_original_text_and_owner_turns_without_model_copying():
    data = sample()
    data["answers"][0]["text"] = "  原始内容，标点与换行保持。\n" * 8 + "尾句。"
    refs, spans = evidence_spans(data)
    assert "".join(s["text"] for s in spans[data["answers"][0]["id"]]) == data["answers"][0]["text"]
    assert all(0 < len(r["quote"]) <= 40 for r in refs.values())
    raw = referenced_output(data)
    original = deepcopy(raw)
    schema, _, _, validate = prepare("report", data)
    wire = schema.model_json_schema()
    for name in ("Evidence", "RatingEvidence", "Improvement"):
        assert "evidence_ref" in wire["$defs"][name]["required"]
        assert "quote" not in wire["$defs"][name]["properties"]
        assert "answer_id" not in wire["$defs"][name]["properties"]
    assert "question_id" not in wire["$defs"]["Improvement"]["properties"]
    parsed = schema.model_validate(raw, strict=True)
    validate(parsed)
    assert raw == original
    first = raw["questions"][0]["strengths"][0]["evidence_ref"]
    assert parsed.questions[0].strengths[0].quote == refs[first]["quote"]
    assert parsed.improvements[0].question_id == "q1"
    raw["improvements"][0]["question_id"] = "q1f1"
    parsed = schema.model_validate(raw, strict=True)
    validate(parsed)
    assert parsed.improvements[0].question_id == "q1"


@pytest.mark.parametrize("failure", ["unknown_ref", "conflicting_quote", "cross_group_ref", "wrong_known_question"])
def test_reference_binding_cannot_hide_invented_or_cross_group_evidence(failure):
    data = sample()
    raw = referenced_output(data)
    item = raw["questions"][0]["strengths"][0]
    if failure == "unknown_ref":
        item["evidence_ref"] = "not-a-real-reference"
    elif failure == "conflicting_quote":
        item["quote"] = "这段内容不存在"
    elif failure == "wrong_known_question":
        raw["improvements"][0]["question_id"] = "q2"
    else:
        _, spans = evidence_spans(data)
        item["evidence_ref"] = spans["a-q2"][0]["id"]
    schema, _, _, validate = prepare("report", data)
    with pytest.raises(ValueError):
        validate(schema.model_validate(raw, strict=True))


def test_report_retry_can_recover_an_older_valid_candidate_without_new_calls_or_fees(training):
    h, headers, *_, fake, _ = training
    row = wait(training, start(training).json()["training"]["id"], lambda r: r["phase"] == "answering")
    with h.app.state.session_factory.begin() as db:
        saved = db.get(Training, row["id"])
        for q in db.scalars(select(TrainingQuestion).where(TrainingQuestion.training_id == saved.id)):
            db.add(TrainingAnswer(training_id=saved.id, question_id=q.id, text="我先明确约束，再验证方案。",
                                  request_key=q.id, fingerprint="d" * 64, method="keyboard", skipped=False))
        db.flush()
        data = report_input(db, saved)
        data["interview_policy"] = saved.scoring_snapshot["interviewPolicy"]
        job = GenerationJob(owner_id=saved.owner_id, training_id=saved.id, kind="report",
                            step_key=saved.id + ":report", state="failed", attempts=2,
                            error_code="MODEL_OUTPUT_INVALID", input_snapshot=data)
        db.add(job)
        saved.status, saved.phase, saved.report_state = "completed", "finished", "failed"
        db.flush()
        job_id, owner_id = job.id, saved.owner_id
    output, _ = generated(data)
    output.improvements = []
    detail = diagnostic(ValueError("Report omits or invents answered questions"), "contract")
    guard = BudgetGuard(h.app.state.engine, h.app.state.settings)
    ids = []
    for attempt in (1, 2):
        spend = guard.reserve(request_key=f"{job_id}-attempt-{attempt}", fingerprint="c" * 64,
            owner_id=owner_id, purpose="report", model="deepseek-flash", maximum_micro=1000, pricing={})
        guard.dispatch(spend.id)
        guard.settle(spend.id, amount_micro=100, usage=(10, 10, 0),
                     result=rejected_result(output, detail) if attempt == 1 else None,
                     error_code="MODEL_OUTPUT_INVALID", duration_ms=1, provider_id="offline-report")
        ids.append(spend.id)
    fake.fail = "MODEL_OUTPUT_INVALID"
    before = deepcopy(guard.summary())
    assert h.client.post(f"/api/v1/training/jobs/{job_id}/retry", json={"confirmed": True}, headers=headers).status_code == 200
    row = wait(training, row["id"], lambda value: value["reportState"] == "ready")
    assert row["report"] and fake.calls == ["question"]
    assert guard.summary() == before
    with h.app.state.session_factory() as db:
        job = db.get(GenerationJob, job_id)
        assert job.attempts == 2 and job.diagnostic["sourceSpendId"] == ids[0]
        assert all(db.get(ModelSpend, key).state == "failed" for key in ids)
    assert read(training, row["id"])["reportState"] == "ready"


@pytest.mark.parametrize("conflict", [False, True])
def test_provider_boundary_parses_per_turn_rows_but_never_publishes_conflicting_ratings(model, conflict, caplog):
    data = sample()
    result, _ = generated(data)
    raw = result.model_dump()
    extras = deepcopy(raw["ratings"])
    for item in extras:
        item["question_id"] += "f1"
    if conflict:
        extras[0]["dimensions"][0]["level"] = 0
    raw["ratings"] += extras
    schema, prompt, content, validate = prepare("report", data)
    gate, requests = gateway(model, post=lambda _: reply(output=raw))
    kwargs = {"request_key": "synthetic-grouped-report-boundary-001", "purpose": "report",
              "system": prompt, "content": content, "schema": schema, "validate": validate,
              "max_output": 8192}
    if conflict:
        with pytest.raises(ApiError) as error:
            gate.generate(**kwargs)
        assert error.value.diagnostic["rule"] == "RATING_GROUPS_CONFLICT"
        with gate.guard.factory() as db:
            record = db.scalar(select(ModelSpend))
            assert record.state == "failed" and record.diagnostic["stage"] == "contract"
            assert record.result["output"] == raw
    else:
        accepted = gate.generate(**kwargs)
        assert len(accepted["output"].ratings) == 5
    assert posts(requests) == 1
    assert "第1组第0次作答" not in caplog.text
