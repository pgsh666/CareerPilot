"""Revalidate already charged, private candidates without another provider call."""
import json

from sqlalchemy import select
from test_training import read, start, wait
from test_training import training as training
from training_support import FakeGateway

from app.model_budget import BudgetGuard
from app.model_validation import diagnostic, rejected_result
from app.models import GenerationJob, ModelSpend, TrainingQuestion
from app.training_prompts import prepare


def rejected_plan(training, *, invalid=False, composite=False):
    h, _, *_, fake, _speech = training
    fake.fail = "MODEL_OUTPUT_INVALID"
    row = wait(training, start(training).json()["training"]["id"],
               lambda r: any(j["state"] == "failed" for j in r["jobs"]))
    with h.app.state.session_factory() as db:
        job = db.scalar(select(GenerationJob).where(GenerationJob.training_id == row["id"], GenerationJob.kind == "plan"))
        job_id, data, key = job.id, job.input_snapshot, h.app.state.generation.call_key(job)
    schema, _, content, _ = prepare("plan", data)
    output = FakeGateway().generate(schema=schema, content=content, purpose="question")["output"]
    output.questions[0].text = "1. 你在这段经历中负责什么？能举一个具体例子吗？"
    if invalid:
        output.questions[1].category = "experience"
    if composite:
        question = next(q for q in output.questions if q.category == "jd_requirement")
        question.requirement_focus = "Python / MySQL"
        question.text = "能分享一次你使用MySQL解决实际问题的经历吗？"
    detail = diagnostic(ValueError("JD focus must occur in both the requirement and the actual question"
                                   if composite else "Ask one concise conversational question at a time"), "contract")
    guard = BudgetGuard(h.app.state.engine, h.app.state.settings)
    spend = guard.reserve(request_key=key, fingerprint="a" * 64, owner_id=h.user().id,
                          purpose="question", model="deepseek-flash", maximum_micro=1000, pricing={})
    guard.dispatch(spend.id)
    guard.settle(spend.id, amount_micro=100, usage=(10, 10, 0), result=rejected_result(output, detail),
                 error_code="MODEL_OUTPUT_INVALID", duration_ms=1, provider_id="offline-private-candidate")
    return row, job_id, spend.id, guard


def test_manual_retry_first_revalidates_private_output_without_another_call_or_fee(training):
    h, headers, *_, fake, _speech = training
    row, job_id, spend_id, guard = rejected_plan(training)
    before = guard.summary()["test"]
    response = h.client.post(f"/api/v1/training/jobs/{job_id}/retry", json={"confirmed": True}, headers=headers)
    assert response.status_code == 200
    row = wait(training, row["id"], lambda r: r["phase"] == "answering")
    assert "具体例子" in row["currentQuestion"]["text"]
    assert fake.calls == ["question"]  # Still configured to fail any new model call.
    after = guard.summary()["test"]
    assert before["sentCalls"] == after["sentCalls"] == 1
    assert before["chargedUpperMicroCny"] == after["chargedUpperMicroCny"] == 100
    with h.app.state.session_factory() as db:
        job, spend = db.get(GenerationJob, job_id), db.get(ModelSpend, spend_id)
        assert job.state == "succeeded" and job.attempts == 1
        assert spend.state == "failed" and spend.error_code == "MODEL_OUTPUT_INVALID"
        assert spend.charged_micro == 100


def test_polling_does_not_apply_a_rejected_candidate_or_generate_again(training):
    row, job_id, _spend_id, _guard = rejected_plan(training)
    h, *_, fake, _speech = training
    row = read(training, row["id"])
    assert not row["questions"] and row["currentQuestion"] is None
    assert fake.calls == ["question"]
    with h.app.state.session_factory() as db:
        assert db.get(GenerationJob, job_id).state == "failed"


def test_retry_recovers_composite_jd_focus_without_changing_paid_content_or_charging_again(training):
    h, headers, *_, fake, _speech = training
    row, job_id, spend_id, guard = rejected_plan(training, composite=True)
    before = guard.summary()["test"]
    response = h.client.post(f"/api/v1/training/jobs/{job_id}/retry", json={"confirmed": True}, headers=headers)
    assert response.status_code == 200
    row = wait(training, row["id"], lambda r: r["phase"] == "answering")
    assert fake.calls == ["question"]
    assert guard.summary()["test"] == before
    with h.app.state.session_factory() as db:
        job, spend = db.get(GenerationJob, job_id), db.get(ModelSpend, spend_id)
        question = next(q for q in job.output["questions"] if q["category"] == "jd_requirement")
        saved = db.scalar(select(TrainingQuestion).where(TrainingQuestion.training_id == row["id"],
                                                         TrainingQuestion.main == 2))
        assert question["text"] == saved.text == "能分享一次你使用MySQL解决实际问题的经历吗？"
        assert question["requirement_focus"] == "mysql"
        assert job.attempts == 1 and job.state == "succeeded"
        assert spend.result["output"]["questions"][1]["requirement_focus"] == "Python / MySQL"
        assert spend.state == "failed" and spend.charged_micro == 100


def test_revalidation_keeps_real_coverage_checks_before_manual_regeneration(training):
    h, headers, *_, fake, _speech = training
    row, job_id, spend_id, _guard = rejected_plan(training, invalid=True)
    fake.fail = None
    assert h.client.post(f"/api/v1/training/jobs/{job_id}/retry", json={"confirmed": True}, headers=headers).status_code == 200
    row = wait(training, row["id"], lambda r: r["phase"] == "answering")
    assert fake.calls == ["question", "question"]
    with h.app.state.session_factory() as db:
        job, spend = db.get(GenerationJob, job_id), db.get(ModelSpend, spend_id)
        assert job.attempts == 2 and job.state == "succeeded"
        assert spend.charged_micro == 100 and spend.state == "failed"
        assert json.dumps(job.output) != json.dumps(spend.result["output"])
