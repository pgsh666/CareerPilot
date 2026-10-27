import json
from datetime import timedelta

import pytest
from test_training import start, wait
from test_training import training as training

from app.model_budget import BudgetGuard
from app.models import GenerationJob, ModelSpend, now_utc
from app.operation_diagnostics import backfill_log_diagnostics

PRIVATE = "private-resume-answer-key-do-not-expose"


def seed(training, *, success=True):
    h = training[0]
    row = wait(training, start(training).json()["training"]["id"], lambda r: r["phase"] == "answering")
    job_id = row["jobs"][0]["id"]
    owner = h.user().id
    guard = BudgetGuard(h.app.state.engine, h.app.state.settings)
    ids = []
    detail = {"stage": "schema", "rule": "SCHEMA_INVALID", "issues": [
        {"path": ["questions", 2, "dimension_ids"], "type": "missing"}], "privateInput": PRIVATE}
    for attempt in (1, 2):
        spend = guard.reserve(request_key=f"{job_id}-attempt-{attempt}", fingerprint="b" * 64, owner_id=owner,
                              purpose="question", model="deepseek-flash", maximum_micro=1000, pricing={})
        guard.dispatch(spend.id)
        guard.settle(spend.id, amount_micro=attempt * 100, usage=(100, 20, 10),
                     result={"privateModelText": PRIVATE}, error_code="MODEL_OUTPUT_INVALID" if attempt == 1 else None,
                     duration_ms=5000, provider_id=f"synthetic-provider-{attempt}",
                     diagnostic=detail if attempt == 1 else None)
        ids.append(spend.id)
    with h.app.state.session_factory.begin() as db:
        job = db.get(GenerationJob, job_id)
        job.attempts = 2
        job.input_snapshot = {**job.input_snapshot, "privateMaterial": PRIVATE}
        job.output = {**job.output, "privateModelText": PRIVATE}
        job.started_at, job.finished_at = now_utc() - timedelta(seconds=5), now_utc()
        if not success:
            job.state, job.error_code, job.error_message = "failed", "MODEL_OUTPUT_INVALID", "返回校验失败"
        else:
            job.state, job.error_code, job.error_message = "succeeded", None, None
    return job_id, ids, guard


def admin(h):
    h.make_admin()
    h.login("admin@example.org")


def test_successful_task_detail_keeps_all_attempts_failure_diagnostic_and_finance(training):
    h = training[0]
    job_id, ids, guard = seed(training)
    before = guard.summary()
    admin(h)
    response = h.client.get(f"/api/v1/admin/tasks/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["task"]["state"] == "succeeded" and data["task"]["errorCode"] is None
    assert data["task"]["attempts"] == 2 and data["callCount"] == 2
    assert data["chargedUpperMicroCny"] == 300 and data["unknownCallCount"] == 0
    assert {call["attempt"] for call in data["calls"]} == {1, 2}
    failed = next(call for call in data["calls"] if call["state"] == "failed")
    assert failed["diagnostic"]["rule"] == "SCHEMA_INVALID"
    assert failed["diagnostic"]["issues"][0]["path"] == "questions[2].dimension_ids"
    assert failed["diagnostic"]["raw"]["issues"][0]["type"] == "missing"
    assert failed["providerRequestId"] == "synthetic-provider-1"
    assert failed["promptTokens"] == 100 and failed["totalTokens"] == 120
    assert failed["durationMs"] == 5000 and failed["createdAt"].endswith("Z")
    assert PRIVATE not in response.text
    linked = h.client.get(f"/api/v1/admin/usage/{ids[0]}").json()
    assert linked["selectedCallId"] == ids[0] and linked["task"]["id"] == job_id
    assert linked["callCount"] == 2
    assert guard.summary() == before


@pytest.mark.parametrize("path", ["/api/v1/admin/tasks/not-found", "/api/v1/admin/usage/not-found"])
def test_operation_details_are_admin_only(h, path):
    assert h.client.get(path).status_code == 401
    h.register()
    h.login()
    assert h.client.get(path).status_code == 403
    admin(h)
    assert h.client.get(path).status_code == 404


def test_unknown_call_does_not_turn_unknown_money_or_missing_diagnostics_into_zero(training):
    h = training[0]
    guard = BudgetGuard(h.app.state.engine, h.app.state.settings)
    spend = guard.reserve(request_key="synthetic-standalone-unknown-001", fingerprint="c" * 64,
                          owner_id=h.user().id, purpose="question", model="deepseek-flash", maximum_micro=1000, pricing={})
    guard.dispatch(spend.id)
    guard.unknown(spend.id, "MODEL_COST_UNCERTAIN", 1000)
    admin(h)
    data = h.client.get(f"/api/v1/admin/usage/{spend.id}").json()
    assert data["task"] is None and data["unknownCallCount"] == 1
    call = data["calls"][0]
    assert call["chargedUpperMicroCny"] is None and call["totalTokens"] is None
    assert call["diagnostic"]["availability"] == "not_recorded" and call["diagnostic"]["raw"] is None


def test_unsafe_diagnostic_fields_never_escape_the_admin_detail(training):
    h = training[0]
    job_id, ids, _ = seed(training, success=False)
    with h.app.state.session_factory.begin() as db:
        spend = db.get(ModelSpend, ids[0])
        spend.diagnostic = {"stage": "schema", "rule": "SCHEMA_INVALID", "input": PRIVATE,
                            "issues": [{"path": ["questions", 0, PRIVATE], "type": "extra_forbidden", "input": PRIVATE}]}
    admin(h)
    response = h.client.get(f"/api/v1/admin/tasks/{job_id}")
    assert response.status_code == 200 and PRIVATE not in response.text
    first = next(call for call in response.json()["calls"] if call["id"] == ids[0])
    assert first["diagnostic"]["raw"]["issues"][0]["path"] == ["questions", 0, "_"]


def test_backfill_uses_only_recorded_safe_log_diagnostics_and_is_idempotent(training):
    h = training[0]
    job_id, ids, _ = seed(training, success=False)
    detail = {"stage": "contract", "rule": "COMPOUND_QUESTION", "signature": "a" * 12, "privateText": PRIVATE}
    line = f'model_output_rejected request_key={job_id}-attempt-2 diagnostic={json.dumps(detail)}'
    with h.app.state.session_factory.begin() as db:
        spend = db.get(ModelSpend, ids[1])
        spend.state, spend.error_code, spend.result = "failed", "MODEL_OUTPUT_INVALID", None
        original_amount = spend.charged_micro
        counts = backfill_log_diagnostics(db, ["unrelated private log", line, line])
        assert counts["callsUpdated"] == counts["tasksUpdated"] == 1
        assert spend.charged_micro == original_amount and "privateText" not in spend.diagnostic
        assert db.get(GenerationJob, job_id).diagnostic["rule"] == "COMPOUND_QUESTION"
    admin(h)
    data = h.client.get(f"/api/v1/admin/tasks/{job_id}").json()
    assert data["task"]["diagnostic"]["rule"] == "COMPOUND_QUESTION"
    assert PRIVATE not in json.dumps(data)
