"""Single-attempt DeepSeek JSON gateway. It has no public free-form prompting endpoint."""
import asyncio
import hashlib
import json
import logging
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from threading import BoundedSemaphore, Lock
from time import monotonic, sleep

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.errors import ApiError
from app.model_budget import BudgetGuard
from app.model_pricing import load as load_pricing
from app.model_validation import diagnostic, public_message, rejected_result

logger = logging.getLogger("careerpilot")

_slot_lock = Lock()
_local_slots = {}

BASE_URL = "https://api.deepseek.com"
CONTEXT_TOKENS = 1_048_576
PRICE_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
PURPOSES = {"integration_smoke", "resume_parse", "jd_parse", "question", "followup",
            "feedback", "report", "practice_feedback"}


def local_date():
    return datetime.now(UTC).astimezone(timezone(timedelta(hours=8))).date()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def usage_cost(data, maximum_output, pricing=None):
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("Missing usage")
    prompt, output, total = (usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
    cached = usage.get("prompt_cache_hit_tokens", usage.get("prompt_tokens_details", {}).get("cached_tokens", 0))
    if any(not isinstance(n, int) or isinstance(n, bool) for n in (prompt, output, total, cached)):
        raise ValueError("Invalid token accounting")
    if not (0 <= cached <= prompt <= CONTEXT_TOKENS and 0 <= output <= maximum_output
            and total == prompt + output):
        raise ValueError("Usage exceeds request bounds")
    miss = usage.get("prompt_cache_miss_tokens", prompt - cached)
    if isinstance(miss, bool) or not isinstance(miss, int) or miss + cached != prompt:
        raise ValueError("Invalid cache accounting")
    # CNY per million tokens equals micro-CNY per token. Peak rates deliberately overestimate
    # any off-peak discounts; this is labelled an estimate, never a provider invoice amount.
    prices = pricing or {"cacheMissPerMillion": "2", "cacheHitPerMillion": "0.04", "outputPerMillion": "8"}
    cost = (Decimal(prompt - cached) * Decimal(prices["cacheMissPerMillion"])
            + Decimal(cached) * Decimal(prices["cacheHitPerMillion"])
            + Decimal(output) * Decimal(prices["outputPerMillion"]))
    return int(cost.to_integral_value(rounding=ROUND_CEILING)), (prompt, output, cached)


class DeepSeekGateway:
    def __init__(self, engine, settings: Settings, *, transport=None):
        self.settings = settings
        self.engine = engine
        self.guard = BudgetGuard(engine, settings)
        self.transport = transport

    @contextmanager
    def model_slot(self):
        """Two local requests; MySQL advisory locks also coordinate maintenance processes."""
        if self.engine.dialect.name != "mysql":
            with _slot_lock:
                slot = _local_slots.setdefault(str(self.engine.url), BoundedSemaphore(2))
            with slot:
                yield
            return
        from sqlalchemy import text
        identity = hashlib.sha256(str(self.engine.url.database).encode()).hexdigest()[:20]
        acquired = None
        with self.engine.connect() as connection:
            try:
                while acquired is None:
                    for i in range(2):
                        name = f"careerpilot:{identity}:model:{i}"
                        if connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": name}) == 1:
                            acquired = name
                            break
                    if acquired is None:
                        sleep(0.1)
                yield
            finally:
                if acquired is not None:
                    connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": acquired})

    async def bounded_post(self, headers, body):
        # An outer deadline covers the complete response, rather than each individual read.
        async with asyncio.timeout(self.settings.model_timeout_seconds):
            async with httpx.AsyncClient(base_url=BASE_URL, headers=headers,
                                         timeout=self.settings.model_timeout_seconds,
                                         trust_env=False, follow_redirects=False,
                                         transport=self.transport) as client:
                return await client.post("/chat/completions", json=body)

    def _cached(self, row, schema, validate):
        if row.state == "succeeded":
            if row.result is None:
                raise ApiError(409, "MODEL_RESULT_NOT_RESTORED", "费用记录已保留，但个人模型缓存未恢复；未自动重新调用")
            output = schema.model_validate(row.result, strict=True)
            if validate:
                validate(output)
            return {"id": row.id, "output": output, "chargedUpperMicroCny": row.charged_micro,
                    "cached": True}
        if row.state != "reserved":
            raise ApiError(409, row.error_code or "MODEL_REQUEST_ALREADY_HANDLED",
                           "该模型请求已处理或费用待核实，不会自动重复付费调用")
        return None

    def generate(self, *, request_key: str, purpose: str, system: str, content: str,
                 schema: type[BaseModel], owner_id=None, max_output=None,
                 policy_version="json-v1", validate=None):
        s = self.settings
        if purpose not in PURPOSES or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_key):
            raise ValueError("Invalid internal model task")
        maximum = max_output if max_output is not None else s.model_max_output_tokens
        allowed_output = s.model_report_max_output_tokens if purpose == "report" else s.model_max_output_tokens
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= allowed_output:
            raise ValueError("Invalid output bound")
        if len((system + content).encode("utf-8")) > 750_000:
            raise ApiError(422, "MODEL_INPUT_TOO_LONG", "材料超过模型处理上限，请精简后重试")
        if not s.deepseek_api_key or not s.deepseek_api_key.get_secret_value().strip():
            raise ApiError(503, "MODEL_NOT_CONFIGURED", "模型密钥尚未配置，未发起付费调用")
        secret = s.deepseek_api_key.get_secret_value().strip()
        if not re.fullmatch(r"[\x21-\x7e]{16,512}", secret):
            raise ApiError(503, "MODEL_KEY_INVALID", "模型密钥格式不正确，未发起付费调用")
        pricing_configuration = load_pricing(s)
        from datetime import date
        age = (local_date() - date.fromisoformat(pricing_configuration["verifiedOn"])).days
        if not 0 <= age < 7:
            raise ApiError(503, "MODEL_PRICING_EXPIRED", "模型计价配置需要核对，未发起付费调用")
        body = {"model": s.deepseek_model, "thinking": {"type": "disabled"},
                "messages": [{"role": "system", "content": system + "\n只输出JSON对象，不使用工具。"},
                             {"role": "user", "content": content}],
                "max_tokens": maximum, "response_format": {"type": "json_object"},
                "stream": False}
        digest = fingerprint({"body": body, "schema": schema.model_json_schema(),
                              "policy": policy_version, "usageMode": s.model_usage_mode})
        existing = self.guard.cached(request_key, digest, owner_id)
        if existing:
            result = self._cached(existing, schema, validate)
            if result:
                return result
        pricing = {**pricing_configuration, "currency": "CNY",
                   "method": "peak_upper_estimate", "reservationContextTokens": CONTEXT_TOKENS}
        # Reserve the full documented context at peak input rates plus bounded output. This
        # avoids relying on an approximate tokenizer when enforcing the user's hard allowance.
        row = self.guard.reserve(request_key=request_key, fingerprint=digest, owner_id=owner_id,
                                 purpose=purpose, model=s.deepseek_model,
                                 maximum_micro=max(1, int((CONTEXT_TOKENS * max(Decimal(pricing["cacheMissPerMillion"]), Decimal(pricing["cacheHitPerMillion"]))
                                                      + maximum * Decimal(pricing["outputPerMillion"])).to_integral_value(rounding=ROUND_CEILING))), pricing=pricing)
        result = self._cached(row, schema, validate)
        if result:
            return result
        headers = {"Authorization": "Bearer " + secret}
        try:
            client = httpx.Client(base_url=BASE_URL, headers=headers, timeout=s.model_timeout_seconds,
                                  trust_env=False, follow_redirects=False, transport=self.transport)
        except Exception:
            self.guard.cancel_unsent(row.id, "MODEL_CLIENT_UNAVAILABLE")
            raise ApiError(503, "MODEL_CLIENT_UNAVAILABLE", "模型连接尚未建立，未发起付费调用") from None
        with client:
            try:
                balance = client.get("/user/balance")
                if balance.status_code != 200:
                    raise ApiError(503, "MODEL_BALANCE_UNAVAILABLE", "模型余额检查失败，未发起付费调用")
                info = balance.json()
                available = any(item.get("currency") == "CNY"
                                and Decimal(item.get("total_balance", "0")).is_finite()
                                and Decimal(item.get("total_balance", "0")) > 0
                                for item in info.get("balance_infos", []))
                if info.get("is_available") is not True or not available:
                    raise ApiError(503, "MODEL_BALANCE_INSUFFICIENT", "模型账户余额不足或币种不匹配，未发起付费调用")
            except Exception as error:
                code = error.code if isinstance(error, ApiError) else "MODEL_BALANCE_UNAVAILABLE"
                self.guard.cancel_unsent(row.id, code)
                if isinstance(error, ApiError):
                    raise
                raise ApiError(503, code, "模型余额暂不可查询，未发起付费调用") from None
            started = monotonic()
            dispatched = False
            try:
                with self.model_slot():
                    self.guard.dispatch(row.id)
                    dispatched = True
                    started = monotonic()
                    response = asyncio.run(self.bounded_post(headers, body))
                elapsed = int((monotonic() - started) * 1000)
                if response.status_code != 200:
                    raise ValueError("Provider did not return usage")
                if len(response.content) > 2 * 1024 * 1024:
                    raise ValueError("Unexpected provider response size")
                data = response.json()
                if "flash" not in str(data.get("model", "")).lower():
                    raise ValueError("Unexpected model accounting")
                amount, usage = usage_cost(data, maximum, pricing)
            except ApiError as error:
                if not dispatched:
                    self.guard.cancel_unsent(row.id, error.code)
                    raise
                detail = {"stage": "transport", "rule": "MODEL_COST_UNCERTAIN"}
                self.guard.unknown(row.id, "MODEL_COST_UNCERTAIN", int((monotonic() - started) * 1000), diagnostic=detail)
                raise ApiError(503, "MODEL_COST_UNCERTAIN", "模型请求费用待核实，未自动重试", diagnostic=detail) from None
            except Exception as error:
                if not dispatched:
                    self.guard.cancel_unsent(row.id, "MODEL_CONNECTION_UNAVAILABLE")
                    raise ApiError(503, "MODEL_CONNECTION_UNAVAILABLE", "模型连接尚未就绪，未发起付费调用") from None
                detail = {"stage": "transport", "rule": "TIMEOUT" if isinstance(error, (TimeoutError, httpx.TimeoutException)) else "MODEL_COST_UNCERTAIN"}
                self.guard.unknown(row.id, "MODEL_COST_UNCERTAIN", int((monotonic() - started) * 1000), diagnostic=detail)
                raise ApiError(503, "MODEL_COST_UNCERTAIN",
                               "模型请求未取得完整用量，费用待核实，未自动重试", diagnostic=detail) from None
            output = None
            error_code = None
            failure_detail = None
            stage = "envelope"
            try:
                choice = data["choices"][0]
                if not isinstance(choice, dict):
                    raise ValueError("Invalid response envelope")
                if choice.get("finish_reason") != "stop":
                    raise ValueError("Incomplete generation")
                stage = "json"
                value = json.loads(choice["message"]["content"])
                stage = "schema"
                output = schema.model_validate(value, strict=True)
                if validate:
                    stage = "contract"
                    validate(output)
            except (ValueError, TypeError, KeyError, IndexError, ValidationError) as error:
                error_code = "MODEL_OUTPUT_INVALID"
                failure_detail = diagnostic(error, stage)
                logger.warning("model_output_rejected request_key=%s diagnostic=%s",
                               request_key, json.dumps(failure_detail, ensure_ascii=True))
            try:
                self.guard.settle(row.id, amount_micro=amount, usage=usage,
                                  result=output.model_dump(mode="json") if not error_code else rejected_result(output, failure_detail),
                                  error_code=error_code, duration_ms=elapsed, provider_id=data.get("id"),
                                  diagnostic=failure_detail)
            except Exception:
                self.guard.unknown(row.id, "MODEL_COST_UNCERTAIN", elapsed)
                raise ApiError(503, "MODEL_COST_UNCERTAIN", "模型费用结算待核实，未自动重试") from None
            if error_code:
                raise ApiError(503, error_code, public_message(failure_detail), diagnostic=failure_detail)
            return {"id": row.id, "output": output, "chargedUpperMicroCny": amount, "cached": False}
