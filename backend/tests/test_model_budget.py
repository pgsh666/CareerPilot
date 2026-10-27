from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select

from app.config import Settings
from app.errors import ApiError
from app.model_budget import TEST_BUCKET, BudgetGuard
from app.model_gateway import DeepSeekGateway, local_date
from app.model_smoke import SYNTHETIC_ANSWER, SmokeOutput, validate_smoke
from app.models import ModelBudget, ModelSpend

FAKE_KEY = "test-only-not-a-real-provider-key"
OUTPUT = {"question": "请介绍该项目的目标用户和使用背景？", "quote": "我负责上传接口", "suggestion": "请补充一次具体的异常处理验证过程。"}


@pytest.fixture
def model(h):
    settings = h.app.state.settings
    settings.deepseek_api_key = SecretStr(FAKE_KEY)
    settings.model_pricing_verified_on = local_date()
    return h.app.state.engine, settings


def reply(output=None, **overwrites):
    import json
    data = {"id": "synthetic-provider-id", "model": "deepseek-flash",
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output if output is not None else OUTPUT)}}],
            "usage": {"prompt_tokens": 400, "completion_tokens": 100, "total_tokens": 500,
                      "prompt_cache_hit_tokens": 100, "prompt_cache_miss_tokens": 300}}
    data.update(overwrites)
    return httpx.Response(200, json=data)


def gateway(model, post=None, balance=None):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "api.deepseek.com"
        assert request.headers["authorization"] == "Bearer " + FAKE_KEY
        if request.url.path == "/user/balance":
            return balance or httpx.Response(200, json={"is_available": True, "balance_infos": [{"currency": "CNY", "total_balance": "5.00"}]})
        assert request.url.path == "/chat/completions"
        return post(request) if post else reply()

    engine, settings = model
    return DeepSeekGateway(engine, settings, transport=httpx.MockTransport(handle)), requests


def generate(gate, key="synthetic-model-check-001", **kw):
    return gate.generate(request_key=key, purpose="integration_smoke", system="输出JSON对象。",
                         content=SYNTHETIC_ANSWER, schema=SmokeOutput, validate=validate_smoke, **kw)


def posts(requests):
    return sum(r.method == "POST" for r in requests)


def test_business_calls_share_twenty_cny_without_consuming_two_smoke_allowance(model):
    gate, requests = gateway(model)
    for index in range(3):
        gate.generate(request_key=f'synthetic-business-{index}', purpose='question', system='输出JSON对象。',
                      content=SYNTHETIC_ANSWER, schema=SmokeOutput, validate=validate_smoke)
    assert posts(requests) == 3
    budget = gate.guard.summary()
    assert budget['test']['limitMicroCny'] == 20_000_000 and budget['test']['sentCalls'] == 3
    assert budget['smoke']['sentCalls'] == 0 and budget['smoke']['maxCalls'] == 2


def test_complete_async_response_has_an_overall_deadline_and_no_automatic_retry(model):
    import asyncio
    from time import monotonic

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{'
            await asyncio.sleep(2)
            yield b'}'
    model[1].model_timeout_seconds = 1
    gate, requests = gateway(model, post=lambda _: httpx.Response(200, stream=SlowBody()))
    before = monotonic()
    with pytest.raises(ApiError) as error:
        generate(gate, 'synthetic-overall-deadline-001')
    assert error.value.code == 'MODEL_COST_UNCERTAIN' and monotonic() - before < 1.8
    assert posts(requests) == 1 and gate.guard.summary()['test']['heldMicroCny'] > 0


def test_three_generation_attempts_share_two_actual_request_slots(model):
    from threading import Lock
    from time import sleep
    running = peak = 0
    lock = Lock()
    def post(_):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        sleep(.12)
        with lock:
            running -= 1
        return reply()
    gate, requests = gateway(model, post=post)
    def run(index):
        return gate.generate(request_key=f'synthetic-parallel-slot-{index}', purpose='question', system='JSON',
                             content=SYNTHETIC_ANSWER, schema=SmokeOutput, validate=validate_smoke)
    with ThreadPoolExecutor(max_workers=3) as pool:
        outputs = list(pool.map(run, range(3)))
    assert peak == 2 and len(outputs) == 3 and posts(requests) == 3


def test_success_uses_one_call_and_restart_reuses_persistent_result(model):
    gate, requests = gateway(model)
    first = generate(gate)
    assert first["output"].quote in SYNTHETIC_ANSWER
    assert first["chargedUpperMicroCny"] == 1404
    restored, after_restart = gateway(model)
    cached = generate(restored)
    assert cached["cached"] and cached["id"] == first["id"]
    assert posts(requests) == 1 and not after_restart
    totals = restored.guard.summary()
    assert totals["test"]["chargedUpperMicroCny"] == 1404
    assert totals["test"]["heldMicroCny"] == 0 and totals["test"]["sentCalls"] == 1


def test_budget_limits_and_call_limit_block_before_network(model):
    gate, requests = gateway(model)
    generate(gate, "synthetic-model-check-001")
    generate(gate, "synthetic-model-check-002")
    with pytest.raises(ApiError) as failure:
        generate(gate, "synthetic-model-check-003")
    assert failure.value.code == "MODEL_TEST_LIMIT" and posts(requests) == 2
    assert gate.guard.summary()["test"]["sentCalls"] == 2


@pytest.mark.parametrize("limit", ["test", "monthly"])
def test_insufficient_reservation_does_not_contact_provider(model, limit):
    engine, settings = model
    if limit == "test":
        settings.model_test_budget_cny = Decimal("1")
    else:
        settings.model_monthly_budget_cny = Decimal("1")
    gate, requests = gateway((engine, settings))
    with pytest.raises(ApiError) as failure:
        generate(gate)
    assert failure.value.code in {"MODEL_TEST_LIMIT", "MODEL_MONTH_LIMIT"}
    assert not requests


def test_unknown_timeout_holds_money_and_does_not_retry_or_reset_at_new_month(model, monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("redacted provider timeout")
    gate, requests = gateway(model, post=timeout)
    with pytest.raises(ApiError) as failure:
        generate(gate)
    assert failure.value.code == "MODEL_COST_UNCERTAIN"
    held = gate.guard.summary()["test"]["heldMicroCny"]
    assert held > 2_000_000 and posts(requests) == 1
    with pytest.raises(ApiError):
        generate(gate)
    assert posts(requests) == 1
    monkeypatch.setattr("app.model_budget.month_key", lambda: "month:2099-02")
    restored = BudgetGuard(*model)
    assert restored.summary()["test"]["heldMicroCny"] == held
    with restored.factory() as db:
        row = db.scalar(select(ModelSpend))
        assert row.state == "unknown" and row.charged_micro is None and row.fee_source == "unknown"


def test_invalid_evidence_is_failed_with_known_cost_not_zero(model):
    gate, requests = gateway(model, post=lambda _: reply({**OUTPUT, "quote": "这句话没有在回答中出现"}))
    with pytest.raises(ApiError) as failure:
        generate(gate)
    assert failure.value.code == "MODEL_OUTPUT_INVALID" and posts(requests) == 1
    totals = gate.guard.summary()["test"]
    assert totals["chargedUpperMicroCny"] > 0 and totals["heldMicroCny"] == 0
    with gate.guard.factory() as db:
        row = db.scalar(select(ModelSpend))
        assert row.state == "failed"
        assert row.result["format"] == "careerpilot-rejected-output-v1"
        assert row.result["output"]["quote"] == "这句话没有在回答中出现"
    with pytest.raises(ApiError):
        generate(gate)
    assert posts(requests) == 1


def test_schema_rejection_logs_safe_field_paths_without_private_input(model, caplog):
    gate, requests = gateway(model, post=lambda _: reply({"quote": "private-content-never-log", "suggestion": ""}))
    with pytest.raises(ApiError) as failure:
        generate(gate)
    assert failure.value.code == "MODEL_OUTPUT_INVALID" and posts(requests) == 1
    assert "结构或必要字段" in failure.value.message
    assert "SCHEMA_INVALID" in caplog.text and '"question"' in caplog.text
    assert "private-content-never-log" not in caplog.text and FAKE_KEY not in caplog.text
    assert gate.guard.summary()["test"]["chargedUpperMicroCny"] > 0
    with gate.guard.factory() as db:
        record = db.scalar(select(ModelSpend))
        assert record.diagnostic["rule"] == "SCHEMA_INVALID"
        assert "private-content-never-log" not in str(record.diagnostic)
    with pytest.raises(ApiError):
        generate(gate)
    assert posts(requests) == 1


def test_truncated_response_has_distinct_content_free_diagnostic(model, caplog):
    choices = [{"finish_reason": "length", "message": {"content": "private-partial-output"}}]
    gate, requests = gateway(model, post=lambda _: reply(choices=choices))
    with pytest.raises(ApiError) as failure:
        generate(gate)
    assert "未完整返回" in failure.value.message
    assert "INCOMPLETE_RESPONSE" in caplog.text and "private-partial-output" not in caplog.text
    assert posts(requests) == 1


def test_custom_validation_error_logs_only_signature_not_error_content(model, caplog):
    gate, _ = gateway(model)

    def invalid(_):
        raise ValueError("private-value-in-an-error")

    with pytest.raises(ApiError):
        gate.generate(request_key="synthetic-private-validator-001", purpose="question", system="JSON",
                      content=SYNTHETIC_ANSWER, schema=SmokeOutput, validate=invalid)
    assert "CONTRACT_REJECTED" in caplog.text and "private-value-in-an-error" not in caplog.text


def test_failed_http_without_usage_is_not_assumed_free_and_does_not_leak_key(model, caplog):
    gate, requests = gateway(model, post=lambda _: httpx.Response(500, text=FAKE_KEY))
    with pytest.raises(ApiError) as failure:
        generate(gate)
    assert FAKE_KEY not in caplog.text and FAKE_KEY not in str(failure.value)
    assert gate.guard.summary()["test"]["heldMicroCny"] > 0 and posts(requests) == 1


def test_insufficient_provider_balance_cancels_unsent_reservation(model):
    gate, requests = gateway(model, balance=httpx.Response(200, json={"is_available": False, "balance_infos": []}))
    with pytest.raises(ApiError) as failure:
        generate(gate)
    assert failure.value.code == "MODEL_BALANCE_INSUFFICIENT" and posts(requests) == 0
    summary = gate.guard.summary()["test"]
    assert summary["sentCalls"] == summary["pendingCalls"] == summary["heldMicroCny"] == summary["chargedUpperMicroCny"] == 0


def test_provider_redirect_never_forwards_bearer_to_other_host(model):
    gate, requests = gateway(model, balance=httpx.Response(302, headers={"Location": "https://other.invalid/"}))
    with pytest.raises(ApiError):
        generate(gate)
    assert len(requests) == 1 and posts(requests) == 0


def reserve(guard, key, amount=12_000_000):
    return guard.reserve(request_key=key, fingerprint="a" * 64, owner_id=None,
                         purpose="integration_smoke", model="deepseek-flash",
                         maximum_micro=amount, pricing={"source": "isolated-test"})


def test_concurrent_reservations_cannot_exceed_cumulative_test_money(model):
    guard = BudgetGuard(*model)
    def attempt(n):
        try:
            return reserve(BudgetGuard(*model), f"parallel-test-request-{n:03}").id
        except ApiError:
            return None
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(attempt, range(4)))
    assert sum(r is not None for r in results) == 1
    summary = guard.summary()["test"]
    assert summary["heldMicroCny"] == 12_000_000 and summary["remainingMicroCny"] == 8_000_000
    with guard.factory() as db:
        assert db.scalar(select(func.count()).select_from(ModelSpend)) == 1


def test_concurrent_settlement_cannot_double_charge(model):
    guard = BudgetGuard(*model)
    row = reserve(guard, "parallel-settlement-request", 100_000)
    guard.dispatch(row.id)
    def settle(_):
        try:
            BudgetGuard(*model).settle(row.id, amount_micro=10_000, usage=(100, 100, 0),
                                       result=OUTPUT, error_code=None, duration_ms=1, provider_id="test")
            return True
        except ApiError:
            return False
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert sum(workers.map(settle, range(4))) == 1
    assert guard.summary()["test"]["chargedUpperMicroCny"] == 10_000
    assert guard.summary()["test"]["heldMicroCny"] == 0


def test_restart_and_lowered_configuration_never_replenish_test_budget(model):
    guard = BudgetGuard(*model)
    row = reserve(guard, "persistent-test-request-01", 16_000_000)
    guard.dispatch(row.id)
    guard.unknown(row.id, "MODEL_COST_UNCERTAIN", 1)
    model[1].model_test_budget_cny = Decimal("10")
    again = BudgetGuard(*model)
    assert again.summary()["test"]["remainingMicroCny"] == 0
    with pytest.raises(ApiError):
        reserve(again, "persistent-test-request-02", 1)
    with guard.factory() as db:
        assert db.get(ModelBudget, TEST_BUCKET).held_micro == 16_000_000


def test_reused_request_key_cannot_change_prompt_and_spend_again(model):
    gate, requests = gateway(model)
    generate(gate)
    with pytest.raises(ApiError) as failure:
        gate.generate(request_key="synthetic-model-check-001", purpose="integration_smoke",
                      system="different input", content="different content", schema=SmokeOutput)
    assert failure.value.code == "MODEL_REQUEST_CONFLICT" and posts(requests) == 1


def test_allowance_above_user_cap_is_rejected_by_configuration():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, model_test_budget_cny="20.01")


def test_expired_price_configuration_blocks_before_network(model):
    from datetime import timedelta
    model[1].model_pricing_verified_on = local_date() - timedelta(days=8)
    gate, requests = gateway(model)
    with pytest.raises(ApiError) as failure:
        generate(gate)
    assert failure.value.code == "MODEL_PRICING_EXPIRED" and not requests
