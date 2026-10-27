"""Dated local pricing confirmation. No network/model request is made to confirm pricing."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from app.control_journal import root_for
from app.errors import ApiError

SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
DEFAULT_RATES = {"cacheHitPerMillion": "0.04", "cacheMissPerMillion": "2", "outputPerMillion": "8"}


def validate(value):
    keys = {"model", "source", "verifiedOn", *DEFAULT_RATES}
    if not isinstance(value, dict) or set(value) != keys or value["model"] != "deepseek-flash" or value["source"] != SOURCE:
        raise ValueError("Invalid model pricing configuration")
    date.fromisoformat(value["verifiedOn"])
    for key in DEFAULT_RATES:
        amount = Decimal(value[key])
        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid rate")
    return value


def load(settings):
    path = root_for(settings) / "model-pricing.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "model": "deepseek-flash", "source": SOURCE,
            "verifiedOn": settings.model_pricing_verified_on.isoformat(), **DEFAULT_RATES}
        return validate(value)
    except (OSError, ValueError, TypeError, InvalidOperation):
        raise ApiError(503, "MODEL_PRICING_INVALID", "模型计价配置无效，请在本机核对后再调用") from None


def confirm(settings, *, hit, miss, output, verified_on):
    value = validate({"model": "deepseek-flash", "source": SOURCE, "verifiedOn": verified_on,
                      "cacheHitPerMillion": str(hit), "cacheMissPerMillion": str(miss), "outputPerMillion": str(output)})
    root = root_for(settings)
    root.mkdir(parents=True, exist_ok=True)
    from app.models import new_id
    temporary = root / f"pricing-{new_id()}.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(root / "model-pricing.json")
    return value
