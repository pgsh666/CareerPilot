"""Question composition, source coverage and version isolation without provider calls."""
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_training import keyboard, read, start, wait
from test_training import training as training
from training_support import FakeGateway

from app.interview_policy import VERSION, blueprint
from app.models import GenerationJob, Training
from app.scoring import RULES, snapshot
from app.training_prompts import policy_version, prepare
from app.training_schemas import NaturalQuestionPlan, ScoredQuestionPlan


def context():
    return {
        "resume": {"skills": "产品设计", "projects": [{"name": "课程助手", "responsibility": "需求分析"}],
                   "internships": []},
        "job": {"role": "AI 产品经理", "direction": "AI产品", "name": "AI产品实习生",
                "requirements": "使用过ChatGPT、Claude、Cursor等AI工具，并有深入思考\n能够分析用户需求\n有产品设计经验",
                "responsibilities": "梳理用户场景"},
    }


def contract(count=5, ctx=None):
    ctx = ctx or context()
    return {"count": count, "context": ctx, "scoring": snapshot(ctx["job"]),
            "interview_policy": VERSION, "interview_blueprint": blueprint(count, ctx)}


def proposed(data):
    dims = [d["id"] for d in data["scoring"]["dimensions"][3:]]
    targets = {item["id"]: item for item in data["interview_blueprint"]["requirements"]}
    questions, specialized = [], 0
    for i, slot in enumerate(data["interview_blueprint"]["slots"]):
        target = targets.get(slot.get("requirement_id"))
        if target:
            focus = next(word for word in ("AI工具", "用户需求", "产品设计", "用户场景", "AI产品") if word in target["quote"])
            text = f"能说说一次与{focus}有关的实际经历吗？"
        else:
            focus = ""
            text = {"background": "课程助手主要帮助谁，你负责什么工作？",
                    "experience": "做课程助手时，你是怎么选择首先解决的问题的？",
                    "scenario": "假设用户反馈功能不好用，你会怎么了解问题？"}[slot["category"]]
        selected = [] if slot["category"] == "background" else [dims[specialized % 3]]
        specialized += bool(selected)
        questions.append({"text": f"第{i + 1}题：{text}", "topic": slot["category"], "category": slot["category"],
                          "requirement_id": target["id"] if target else "", "requirement_focus": focus,
                          "basis": [{"kind": "job", "quote": target["quote"] if target else "梳理用户场景"}]
                          if target or slot["category"] == "scenario" else [{"kind": "resume", "quote": "课程助手"}],
                          "dimension_ids": selected, "reference_points": ["说明本题所问的具体做法。"]})
    return {"questions": questions}


@pytest.mark.parametrize(("count", "experience_count", "jd_count", "scenario_count"), [(3, 1, 1, 1), (5, 2, 2, 1), (8, 3, 3, 2)])
def test_question_counts_and_jd_targets_are_locked_locally(count, experience_count, jd_count, scenario_count):
    data = contract(count)
    slots = data["interview_blueprint"]["slots"]
    assert sum(s["category"] in {"background", "experience"} for s in slots) == experience_count
    assert sum(s["category"] == "jd_requirement" for s in slots) == jd_count
    assert sum(s["category"] == "scenario" for s in slots) == scenario_count
    schema, prompt, _, validate = prepare("plan", data)
    assert schema is NaturalQuestionPlan
    assert "深入知识与专业边界留给" in prompt
    validate(schema.model_validate(proposed(data)))


def test_mandatory_requirements_then_ai_tools_take_priority_over_bonus_items():
    ctx = context()
    ctx["job"]["requirements"] = "产品设计经验优先\n必须能够分析用户需求\n使用过ChatGPT、Claude、Cursor等AI工具，并有深入思考"
    plan = blueprint(5, ctx)
    targets = [s["requirement_quote"] for s in plan["slots"] if s["category"] == "jd_requirement"]
    assert targets == ["必须能够分析用户需求", "使用过ChatGPT、Claude、Cursor等AI工具，并有深入思考"]


def test_empty_experience_does_not_allocate_assumed_project_questions():
    ctx = context()
    ctx["resume"] = {"projects": [{}], "internships": [], "skills": "产品设计"}
    data = contract(ctx=ctx)
    assert not data["interview_blueprint"]["has_experience"]
    assert all(s["category"] not in {"background", "experience"} for s in data["interview_blueprint"]["slots"])
    schema, _, _, validate = prepare("plan", data)
    validate(schema.model_validate(proposed(data)))


def test_sparse_jd_reuses_actual_confirmed_topic_without_inventing_requirements():
    ctx = context()
    ctx["job"]["requirements"] = ctx["job"]["responsibilities"] = ""
    plan = blueprint(8, ctx)
    assert len(plan["requirements"]) == 1
    assert plan["requirements"][0]["quote"] == "AI产品"
    assert "换一个实际侧面" in [s for s in plan["slots"] if s["category"] == "jd_requirement"][1]["instruction"]


@pytest.mark.parametrize("failure", ["all_projects", "basis_only", "wrong_requirement", "weak_focus", "bound_project", "tools_omitted", "too_long"])
def test_invalid_composition_and_fake_jd_coverage_are_rejected(failure):
    data = contract()
    value = proposed(data)
    jd = value["questions"][2]
    if failure == "all_projects":
        jd["category"] = "experience"
    elif failure == "basis_only":
        jd["text"] = "你在这段经历中主要负责什么？"
    elif failure == "wrong_requirement":
        jd["requirement_id"] = "jd2"
    elif failure == "weak_focus":
        jd.update(requirement_focus="使用过", text="说说你使用过的东西？")
    elif failure == "bound_project":
        jd["text"] = "你在课程助手项目中如何使用AI工具？"
    elif failure == "tools_omitted":
        jd.update(requirement_focus="深入思考", text="能谈谈你是怎样深入思考的吗？")
    else:
        jd["text"] = "AI工具" + "使用经历" * 40
    schema, _, _, validate = prepare("plan", data)
    with pytest.raises(ValueError):
        validate(schema.model_validate(value))


def test_one_example_tool_can_cover_jd_without_requiring_all_brands():
    data = contract()
    value = proposed(data)
    value["questions"][2].update(requirement_focus="Cursor", text="说说一次用Cursor帮助你完成实际任务的经历？")
    schema, _, _, validate = prepare("plan", data)
    validate(schema.model_validate(value))


def test_real_short_jd_quote_is_accepted_when_it_contains_the_asked_focus():
    data = contract()
    value = proposed(data)
    value["questions"][2]["basis"][0]["quote"] = "ChatGPT、Claude、Cursor等AI工具"
    schema, _, _, validate = prepare("plan", data)
    validate(schema.model_validate(value, strict=True))


def test_short_quote_from_other_requirement_or_without_focus_is_rejected():
    data = contract()
    schema, _, _, validate = prepare("plan", data)
    for quote in ("用户需求", "深入思考"):
        value = proposed(data)
        value["questions"][2]["basis"][0]["quote"] = quote
        with pytest.raises(ValueError):
            validate(schema.model_validate(value, strict=True))


def test_empty_metadata_and_server_added_common_dimensions_are_canonicalized():
    data = contract()
    value = proposed(data)
    value["questions"][0].update(requirement_id=None, requirement_focus=None)
    for question in value["questions"]:
        question["dimension_ids"] = ["relevance", "logic", "evidence", *question["dimension_ids"]]
    schema, _, _, validate = prepare("plan", data)
    result = schema.model_validate(value, strict=True)
    assert result.questions[0].requirement_id == ""
    assert all(not set(q.dimension_ids) & {"relevance", "logic", "evidence"} for q in result.questions)
    validate(result)


def test_new_policy_still_rejects_uncovered_scoring_dimensions():
    data = contract()
    value = proposed(data)
    for question in value["questions"]:
        question["dimension_ids"] = []
    schema, _, _, validate = prepare("plan", data)
    with pytest.raises(ValueError, match="all three"):
        validate(schema.model_validate(value))


def test_old_plan_contract_and_fingerprint_policy_are_preserved():
    data = contract(3)
    data.pop("interview_policy")
    data.pop("interview_blueprint")
    data["scoring"].pop("interviewPolicy")
    data["scoring"].pop("rubricVersion")
    data["scoring"]["version"] = "careerpilot-rubric-v1"
    schema, prompt, _, validate = prepare("plan", data)
    assert schema is ScoredQuestionPlan
    assert "interview_blueprint" not in prompt
    assert policy_version("plan", data) == "training-evidence-v1:plan:careerpilot-rubric-v1"
    FakeGateway().generate(schema=schema, content=json.dumps(data), validate=validate, purpose="question")


def test_new_version_keeps_approved_dimensions_weights_and_bands():
    rule = snapshot(context()["job"])
    assert rule["version"] == "careerpilot-rubric-v1-interview-v2"
    assert rule["rubricVersion"] == RULES["version"]
    assert rule["dimensions"] == RULES["common"] + RULES["roles"]["product"]["dimensions"]


def test_followup_sees_group_history_and_report_does_not_require_unasked_theory():
    data = contract()
    data.update(answer={"text": "我尝试过用Cursor整理代码，但要继续追问验证方法。"}, follow=0)
    schema, prompt, _, validate = prepare("advance", data)
    assert "group_questions/group_answers" in prompt and "一个专业原理" in prompt
    result = schema.model_validate({"action": "followup", "question": "你刚才提到的整理结果，你是怎么验证的？",
                                    "quote": "用Cursor整理代码", "reference_points": ["说明如何判断结果。"]})
    validate(result)
    result.question = "它是怎么工作的？底层原理是什么？"
    validate(result)
    result.question = "验证方法" * 40
    with pytest.raises(ValueError, match="length limit"):
        validate(result)
    _, prompt, _, _ = prepare("report", data)
    assert "没有发生的追问" in prompt and "不能作为缺项或扣分理由" in prompt
    legacy = deepcopy(data)
    legacy.pop("interview_policy")
    _, old_prompt, _, _ = prepare("report", legacy)
    assert "没有发生的追问" not in old_prompt


@pytest.mark.parametrize("text", [
    "1. 能分享一次你使用AI工具完成实际任务的经历吗？",
    "①你平时用过哪些AI工具？选一次具体经历说说可以吗？",
    "你用过ChatGPT吗？能结合一次经历说说你的使用感受吗？",
])
def test_numbering_and_related_invitation_do_not_discard_the_whole_plan(text):
    data = contract()
    value = proposed(data)
    value["questions"][2].update(text=text, requirement_focus="ChatGPT" if "ChatGPT" in text else "AI工具")
    schema, _, _, validate = prepare("plan", data)
    validate(schema.model_validate(value, strict=True))


def test_five_question_service_plan_freezes_blueprint_and_uses_one_call(training):
    h, headers, resume_id, job_id, fake, *_ = training
    source = ("岗位名称：AI产品实习生\n岗位方向：AI产品\n岗位职责：梳理用户场景\n"
              "任职要求：使用过ChatGPT、Claude、Cursor等AI工具，并有深入思考\n能够分析用户需求")
    job = h.client.post("/api/v1/materials/jobs", json={"source": source},
                        headers={**headers, "Idempotency-Key": str(uuid4())}).json()["material"]
    fields = {k: job[k] for k in ("name", "company", "role", "direction", "responsibilities", "requirements", "inference", "useInference")}
    fields.update(role="AI 产品经理", direction="AI产品",
                  requirements="使用过ChatGPT、Claude、Cursor等AI工具，并有深入思考\n能够分析用户需求")
    assert h.client.put(f'/api/v1/materials/jobs/{job["id"]}',
                        json={"revision": job["revision"], "source": source, "fields": fields}, headers=headers).status_code == 200
    job_id = job["id"]
    response = h.client.post("/api/v1/training/interviews",
                             json={"resume_id": resume_id, "job_id": job_id, "count": 5, "confirmed": True},
                             headers={**headers, "Idempotency-Key": str(uuid4())})
    assert response.status_code == 201
    row = wait(training, response.json()["training"]["id"], lambda r: r["phase"] == "answering")
    with h.app.state.session_factory() as db:
        plan = db.scalar(select(GenerationJob).where(GenerationJob.training_id == row["id"], GenerationJob.kind == "plan"))
        assert plan.input_snapshot["interview_policy"] == VERSION
        assert [q["category"] for q in plan.output["questions"]] == ["background", "experience", "jd_requirement", "jd_requirement", "scenario"]
        assert "ChatGPT" in plan.output["questions"][2]["text"]
        assert "深入思考" in plan.output["questions"][2]["basis"][0]["quote"]
        assert db.get(Training, row["id"]).scoring_snapshot["interviewPolicy"] == VERSION
    assert fake.calls == ["question"]
    assert len(row["questions"]) == 1


def test_rejected_plan_is_not_shown_or_automatically_regenerated(training):
    class InvalidPlanGateway(FakeGateway):
        def generate(self, **kwargs):
            original = kwargs["validate"]

            def invalid(result):
                result.questions[1].category = "experience"
                original(result)

            return super().generate(**{**kwargs, "validate": invalid})

    h, *_ = training
    fake = InvalidPlanGateway()
    h.app.state.generation.gateway_factory = lambda *_: fake
    row = wait(training, start(training).json()["training"]["id"],
               lambda r: any(j["state"] == "failed" for j in r["jobs"]))
    assert not row["questions"] and row["currentQuestion"] is None
    assert fake.calls == ["question"]
    read(training, row["id"])
    assert fake.calls == ["question"]


def test_hypothetical_answer_can_receive_followup_and_group_context_is_saved(training):
    row = wait(training, start(training).json()["training"]["id"], lambda r: r["phase"] == "answering")
    assert keyboard(training, row, "没有做过，但我会先验证输入和返回结果，还想继续追问具体方法。").status_code == 200
    row = wait(training, row["id"], lambda r: r["phase"] == "answering")
    assert row["currentQuestion"]["follow"] == 1
    h = training[0]
    with h.app.state.session_factory() as db:
        follow = db.scalar(select(GenerationJob).where(GenerationJob.training_id == row["id"], GenerationJob.kind == "advance"))
        assert follow.input_snapshot["interview_policy"] == VERSION
        assert len(follow.input_snapshot["group_questions"]) == 1
        assert "没有做过，但" in follow.input_snapshot["group_answers"][0]["text"]


def test_existing_interview_keeps_old_followup_and_reporting_policy(training):
    row = wait(training, start(training).json()["training"]["id"], lambda r: r["phase"] == "answering")
    h = training[0]
    original_question = row["currentQuestion"]["text"]
    with h.app.state.session_factory.begin() as db:
        stored = db.get(Training, row["id"])
        legacy = dict(stored.scoring_snapshot)
        legacy.pop("interviewPolicy")
        legacy.pop("rubricVersion")
        legacy["version"] = "careerpilot-rubric-v1"
        stored.scoring_snapshot, stored.scoring_version = legacy, legacy["version"]
    assert read(training, row["id"])["currentQuestion"]["text"] == original_question
    assert keyboard(training, row, "我维护上传接口，继续追问验证方法。").status_code == 200
    row = wait(training, row["id"], lambda r: r["phase"] == "answering")
    assert row["scoreVersion"] == "careerpilot-rubric-v1"
    with h.app.state.session_factory() as db:
        follow = db.scalar(select(GenerationJob).where(GenerationJob.training_id == row["id"], GenerationJob.kind == "advance"))
        assert "interview_policy" not in follow.input_snapshot
        assert "group_questions" not in follow.input_snapshot
