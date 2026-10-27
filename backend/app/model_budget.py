"""Money is integer micro-CNY. Reservations survive restarts, unknown fees never become zero."""
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import session_factory
from app.errors import ApiError
from app.maintenance_storage import checkpointed
from app.models import (
    AuthSession,
    FeeAdjustment,
    GenerationJob,
    ModelBudget,
    ModelSpend,
    Training,
    User,
    now_utc,
)

TEST_BUCKET = "tests:careerpilot"
SMOKE_BUCKET = "smoke:careerpilot"
TEST_HARD_CAP_MICRO = 20_000_000


def month_key():
    return "month:" + datetime.now(UTC).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m")


def micro_cny(value: Decimal):
    return int((value * 1_000_000).to_integral_value(rounding=ROUND_FLOOR))


class BudgetGuard:
    def __init__(self, engine, settings: Settings):
        self.engine = engine
        self.factory = session_factory(engine)
        self.settings = settings

    def _limits(self, monthly_key, test_mode, smoke=False):
        limits = [(monthly_key, micro_cny(self.settings.model_monthly_budget_cny), None)]
        if test_mode:
            limits.append((TEST_BUCKET, min(TEST_HARD_CAP_MICRO, micro_cny(self.settings.model_test_budget_cny)), None))
            if smoke:
                limits.append((SMOKE_BUCKET, TEST_HARD_CAP_MICRO, self.settings.model_test_max_calls))
        return limits

    def cached(self, request_key, fingerprint, owner_id):
        with self.factory() as db:
            row = db.scalar(select(ModelSpend).where(ModelSpend.request_key == request_key))
            if row and (row.fingerprint != fingerprint or row.owner_id != owner_id):
                raise ApiError(409, "MODEL_REQUEST_CONFLICT", "请求编号已用于不同内容")
            return row

    def reserve(self, *, request_key, fingerprint, owner_id, purpose, model, maximum_micro, pricing):
        if not isinstance(maximum_micro, int) or isinstance(maximum_micro, bool) or maximum_micro <= 0:
            raise ValueError("An explicit positive upper reservation is required")
        key, testing = month_key(), self.settings.model_usage_mode == "test"
        try:
            with self.factory.begin() as db:
                existing = db.scalar(select(ModelSpend).where(ModelSpend.request_key == request_key))
                if existing:
                    if existing.fingerprint != fingerprint or existing.owner_id != owner_id:
                        raise ApiError(409, "MODEL_REQUEST_CONFLICT", "请求编号已用于不同内容")
                    return existing
                for bucket_key, configured_limit, max_calls in self._limits(key, testing, purpose == "integration_smoke"):
                    bucket = db.get(ModelBudget, bucket_key)
                    if not bucket:
                        try:
                            with db.begin_nested():
                                db.add(ModelBudget(key=bucket_key, limit_micro=configured_limit,
                                                   max_calls=max_calls))
                                db.flush()
                        except IntegrityError:
                            pass
                        bucket = db.get(ModelBudget, bucket_key)
                    effective_limit = min(bucket.limit_micro, configured_limit)
                    conditions = [ModelBudget.key == bucket_key,
                                  ModelBudget.charged_micro + ModelBudget.held_micro + maximum_micro <= effective_limit]
                    if max_calls is not None:
                        call_limit = min(bucket.max_calls if bucket.max_calls is not None else max_calls, max_calls)
                        conditions.append(ModelBudget.sent_calls + ModelBudget.pending_calls < call_limit)
                    changed = db.execute(update(ModelBudget).where(*conditions).values(
                        held_micro=ModelBudget.held_micro + maximum_micro,
                        pending_calls=ModelBudget.pending_calls + 1,
                    ), execution_options={"synchronize_session": False})
                    if changed.rowcount != 1:
                        code = "MODEL_TEST_LIMIT" if bucket_key != key else "MODEL_MONTH_LIMIT"
                        message = ("测试调用次数或累计测试额度已达上限，未发起付费调用"
                                   if bucket_key != key else "本月模型额度不足，未发起付费调用")
                        raise ApiError(429, code, message)
                row = ModelSpend(request_key=request_key, fingerprint=fingerprint, owner_id=owner_id,
                                 purpose=purpose, provider="deepseek", model=model, month_key=key,
                                 test_mode=testing, reserved_micro=maximum_micro, pricing=pricing)
                db.add(row)
                db.flush()
                return row
        except IntegrityError:
            existing = self.cached(request_key, fingerprint, owner_id)
            if existing:
                return existing
            raise

    def _row(self, db, spend_id):
        row = db.scalar(select(ModelSpend).where(ModelSpend.id == spend_id).with_for_update())
        if row is None:
            raise ApiError(409, "MODEL_RESERVATION_MISSING", "模型费用预留不存在，未继续调用")
        return row

    @checkpointed(required=True)
    def dispatch(self, spend_id):
        with self.factory.begin() as db:
            initial = db.get(ModelSpend, spend_id)
            if initial and initial.pricing.get("personalDataPurged"):
                raise ApiError(409, "MODEL_CONTENT_REMOVED", "调用对应的材料已清理，未发起付费调用")
            if initial and initial.owner_id:
                owner = db.scalar(select(User).where(User.id == initial.owner_id).with_for_update())
                if not owner or not owner.enabled or owner.closed_at:
                    raise ApiError(403, "ACCOUNT_UNAVAILABLE", "账号不可用，未发起新的付费调用")
                if "-attempt-" in initial.request_key:
                    job = db.get(GenerationJob, initial.request_key.rsplit("-attempt-", 1)[0])
                    if not job or job.state == "stale":
                        raise ApiError(409, "MODEL_CONTENT_REMOVED", "调用对应的任务已失效，未发起付费调用")
                    if job and job.auth_session_id:
                        auth = db.scalar(select(AuthSession).where(AuthSession.id == job.auth_session_id).with_for_update())
                        if not auth or auth.revoked_at or auth.expires_at <= now_utc():
                            raise ApiError(401, "SESSION_EXPIRED", "授权已失效，未发起新的付费调用")
                    training = db.get(Training, job.training_id) if job and job.training_id else None
                    if training and training.status == "interrupted":
                        raise ApiError(409, "TRAINING_NOT_ACTIVE", "训练已中断，未发起新的付费调用")
            row = self._row(db, spend_id)
            current_month = month_key()
            if row.state == "reserved" and row.month_key != current_month:
                old_month = row.month_key
                configured = micro_cny(self.settings.model_monthly_budget_cny)
                bucket = db.get(ModelBudget, current_month)
                if not bucket:
                    try:
                        with db.begin_nested():
                            db.add(ModelBudget(key=current_month, limit_micro=configured))
                            db.flush()
                    except IntegrityError:
                        pass
                    bucket = db.get(ModelBudget, current_month)
                changed = db.execute(update(ModelBudget).where(ModelBudget.key == current_month,
                    ModelBudget.charged_micro + ModelBudget.held_micro + row.reserved_micro <= min(bucket.limit_micro, configured))
                    .values(held_micro=ModelBudget.held_micro + row.reserved_micro,
                            pending_calls=ModelBudget.pending_calls + 1))
                if changed.rowcount != 1:
                    raise ApiError(429, "MODEL_MONTH_LIMIT", "新账期额度不足，未发起付费调用")
                db.execute(update(ModelBudget).where(ModelBudget.key == old_month).values(
                    held_micro=ModelBudget.held_micro - row.reserved_micro,
                    pending_calls=ModelBudget.pending_calls - 1))
                row.month_key = current_month
            changed = db.execute(update(ModelSpend).where(ModelSpend.id == spend_id,
                                ModelSpend.state == "reserved").values(state="running", created_at=now_utc()),
                                execution_options={"synchronize_session": False})
            if changed.rowcount != 1:
                raise ApiError(409, "MODEL_ALREADY_STARTED", "该请求已处理，不重复付费调用")
            for key, _, _ in self._limits(row.month_key, row.test_mode, row.purpose == "integration_smoke"):
                db.execute(update(ModelBudget).where(ModelBudget.key == key).values(
                    pending_calls=ModelBudget.pending_calls - 1, sent_calls=ModelBudget.sent_calls + 1))

    @checkpointed()
    def cancel_unsent(self, spend_id, error_code):
        with self.factory.begin() as db:
            row = self._row(db, spend_id)
            if row.state != "reserved":
                return
            changed = db.execute(update(ModelSpend).where(ModelSpend.id == spend_id,
                                 ModelSpend.state == "reserved").values(state="cancelling"),
                                 execution_options={"synchronize_session": False})
            if changed.rowcount != 1:
                return
            for key, _, _ in self._limits(row.month_key, row.test_mode, row.purpose == "integration_smoke"):
                db.execute(update(ModelBudget).where(ModelBudget.key == key).values(
                    held_micro=ModelBudget.held_micro - row.reserved_micro,
                    pending_calls=ModelBudget.pending_calls - 1))
            row.state, row.fee_source, row.charged_micro = "cancelled", "not_sent", 0
            row.error_code, row.finished_at = error_code, now_utc()

    @checkpointed()
    def unknown(self, spend_id, error_code, duration_ms, diagnostic=None):
        with self.factory.begin() as db:
            row = self._row(db, spend_id)
            if row.state == "running":
                changed = db.execute(update(ModelSpend).where(ModelSpend.id == spend_id,
                                     ModelSpend.state == "running").values(state="unknown"),
                                     execution_options={"synchronize_session": False})
                if changed.rowcount != 1:
                    return
                row.state, row.error_code = "unknown", error_code
                from app.model_validation import safe_diagnostic
                row.diagnostic = safe_diagnostic(diagnostic)
                row.finished_at, row.duration_ms = now_utc(), duration_ms
                # All reserved money stays held. Never silently retry or expire uncertain charges.

    @checkpointed()
    def settle(self, spend_id, *, amount_micro, usage, result, error_code, duration_ms, provider_id, diagnostic=None):
        with self.factory.begin() as db:
            row = self._row(db, spend_id)
            if row.state != "running":
                raise ApiError(409, "MODEL_ALREADY_SETTLED", "模型请求已结算，不重复处理")
            if not isinstance(amount_micro, int) or not 0 <= amount_micro <= row.reserved_micro:
                raise ApiError(503, "MODEL_COST_UNCERTAIN", "费用超出预留范围，保留额度待核实")
            changed = db.execute(update(ModelSpend).where(ModelSpend.id == spend_id,
                                 ModelSpend.state == "running").values(state="settling"),
                                 execution_options={"synchronize_session": False})
            if changed.rowcount != 1:
                raise ApiError(409, "MODEL_ALREADY_SETTLED", "模型请求已结算，不重复处理")
            for key, _, _ in self._limits(row.month_key, row.test_mode, row.purpose == "integration_smoke"):
                db.execute(update(ModelBudget).where(ModelBudget.key == key).values(
                    held_micro=ModelBudget.held_micro - row.reserved_micro,
                    charged_micro=ModelBudget.charged_micro + amount_micro))
            row.state = "failed" if error_code else "succeeded"
            row.charged_micro, row.fee_source = amount_micro, "peak_upper_estimate"
            row.prompt_tokens, row.completion_tokens, row.cached_tokens = usage
            row.result, row.error_code = (None if row.pricing.get("personalDataPurged") else result), error_code
            from app.model_validation import safe_diagnostic
            row.diagnostic = safe_diagnostic(diagnostic)
            row.duration_ms, row.finished_at = duration_ms, now_utc()
            row.provider_request_id = provider_id[:128] if isinstance(provider_id, str) else None

    def summary(self):
        result = {}
        with self.factory() as db:
            for key, configured, max_calls in self._limits(month_key(), True, True):
                row = db.get(ModelBudget, key)
                limit = min(row.limit_micro, configured) if row else configured
                charged, held = (row.charged_micro, row.held_micro) if row else (0, 0)
                conditions = (ModelSpend.test_mode.is_(True),) if key == TEST_BUCKET else (
                    (ModelSpend.purpose == "integration_smoke", ModelSpend.test_mode.is_(True)) if key == SMOKE_BUCKET else (ModelSpend.month_key == key,))
                spends = list(db.scalars(select(ModelSpend).where(*conditions)))
                result["test" if key == TEST_BUCKET else "smoke" if key == SMOKE_BUCKET else "month"] = {
                    "limitMicroCny": limit, "chargedUpperMicroCny": charged,
                    "heldMicroCny": held, "remainingMicroCny": max(0, limit - charged - held),
                    "sentCalls": row.sent_calls if row else 0,
                    "pendingCalls": row.pending_calls if row else 0,
                    "estimatedMicroCny": sum(s.charged_micro or 0 for s in spends if s.fee_source == "peak_upper_estimate"),
                    "verifiedMicroCny": sum(s.charged_micro or 0 for s in spends if s.fee_source == "provider_verified"),
                    "unknownHeldMicroCny": sum(s.reserved_micro for s in spends if s.state == "unknown"),
                    "maxCalls": min(row.max_calls, max_calls) if row and row.max_calls is not None and max_calls is not None else max_calls,
                }
        return result

    @checkpointed(required=True)
    def reconcile(self, spend_id, *, amount_micro, evidence_ref):
        import re
        if isinstance(amount_micro, bool) or not isinstance(amount_micro, int) or amount_micro < 0:
            raise ValueError("Reconciliation requires a nonnegative integer micro-CNY amount")
        if not isinstance(evidence_ref, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{4,128}", evidence_ref):
            raise ValueError("Use a nonpersonal invoice/reference ID or document SHA256")
        with self.factory.begin() as db:
            row = self._row(db, spend_id)
            previous = db.scalar(select(FeeAdjustment).where(FeeAdjustment.spend_id == row.id,
                                                              FeeAdjustment.evidence_ref == evidence_ref))
            if previous:
                if previous.amount_micro != amount_micro:
                    raise ApiError(409, "RECONCILIATION_CONFLICT", "同一核实凭据已登记其他金额，未覆盖历史")
                return {"id": previous.id, "reused": True, "amountMicroCny": amount_micro}
            if row.state not in {"unknown", "succeeded", "failed"}:
                raise ApiError(409, "RECONCILIATION_NOT_ALLOWED", "请求尚未结束或未发出，不能按此方式核账")
            original_state, original_amount = row.state, row.charged_micro
            unknown = row.state == "unknown"
            adjustment = FeeAdjustment(spend_id=row.id, evidence_ref=evidence_ref, amount_micro=amount_micro,
                                       previous_amount_micro=original_amount, previous_state=original_state,
                                       previous_error_code=row.error_code)
            db.add(adjustment)
            for key, _, _ in self._limits(row.month_key, row.test_mode, row.purpose == "integration_smoke"):
                values = {"charged_micro": ModelBudget.charged_micro + amount_micro - (original_amount or 0)}
                if unknown:
                    values["held_micro"] = ModelBudget.held_micro - row.reserved_micro
                db.execute(update(ModelBudget).where(ModelBudget.key == key).values(**values))
            row.charged_micro, row.fee_source = amount_micro, "provider_verified"
            if unknown:
                row.state, row.error_code = "failed", "MODEL_FEE_RECONCILED"
                if "-attempt-" in row.request_key:
                    job = db.get(GenerationJob, row.request_key.rsplit("-attempt-", 1)[0])
                    if job and f"{job.id}-attempt-{job.attempts}" == row.request_key:
                        job.error_code, job.error_message = "MODEL_FEE_RECONCILED", "上次费用已核实，符合条件时可手动重试生成。"
            db.flush()
            return {"id": adjustment.id, "reused": False, "amountMicroCny": amount_micro}
