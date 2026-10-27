"""Private backup serialization and an input-free billing checkpoint outside restores."""
import hashlib
import json
import logging
import os
from datetime import date, datetime
from functools import wraps

from sqlalchemy import Date, DateTime, MetaData, inspect, select

from app.control_journal import encoded, journal_lock, root_for
from app.errors import ApiError

logger = logging.getLogger("careerpilot")
FINANCE_TABLES = ("model_budgets", "model_spends", "model_fee_adjustments")


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def read_tables(engine, names=None, *, financial=False):
    existing = inspect(engine).get_table_names()
    selected = [name for name in (names or existing) if name in existing]
    metadata = MetaData()
    metadata.reflect(bind=engine, only=selected)
    result = {}
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN")
        for name in selected:
            table = metadata.tables[name]
            columns = [c for c in table.columns if not (financial and name == "model_spends" and c.name in {"owner_id", "result"})]
            result[name] = [{key: json_value(value) for key, value in row.items()}
                            for row in connection.execute(select(*columns)).mappings()]
        connection.rollback()
    return result


def restore_values(table, rows):
    values = []
    for row in rows:
        if not isinstance(row, dict) or not set(row) <= set(table.columns.keys()):
            raise ApiError(422, "BACKUP_SCHEMA_INVALID", "备份字段与当前数据库结构不兼容")
        value = dict(row)
        for column in table.columns:
            if value.get(column.name) is not None:
                if isinstance(column.type, DateTime):
                    value[column.name] = datetime.fromisoformat(value[column.name])
                elif isinstance(column.type, Date):
                    value[column.name] = date.fromisoformat(value[column.name])
        values.append(value)
    return values


def atomic_json(path, value):
    from app.models import new_id
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + new_id() + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded(value))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_billing(settings, *, required=False):
    path = root_for(settings) / "billing-protection.json"
    if not path.exists():
        if required:
            raise ApiError(409, "LATEST_BILLING_REQUIRED", "缺少最新费用保护记录，不能重置费用台账后开放付费调用")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        signature = value.pop("sha256")
        if hashlib.sha256(encoded(value)).hexdigest() != signature:
            raise ValueError("hash")
        if value["format"] != "careerpilot-billing-v1":
            raise ValueError("format")
        value["sha256"] = signature
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise ApiError(503, "BILLING_PROTECTION_INVALID", "费用保护记录校验失败，未继续恢复或付费调用") from None


def checkpoint_billing(engine, settings):
    from app.models import now_utc
    with journal_lock(settings, "billing"):
        previous = load_billing(settings)
        data = read_tables(engine, FINANCE_TABLES, financial=True)
        if previous:
            previous_ids = {row["id"] for row in previous["tables"].get("model_spends", [])}
            present_ids = {row["id"] for row in data.get("model_spends", [])}
            if not previous_ids <= present_ids:
                raise ApiError(503, "BILLING_RESTORE_REQUIRED", "数据库费用记录早于保护记录，需先恢复核实台账，未继续付费调用")
            previous_adjustments = {r["id"] for r in previous["tables"].get("model_fee_adjustments", [])}
            current_adjustments = {r["id"] for r in data.get("model_fee_adjustments", [])}
            current_spends = {r["id"]: r for r in data.get("model_spends", [])}
            new_adjusted_spends = {r["spend_id"] for r in data.get("model_fee_adjustments", []) if r["id"] not in previous_adjustments}
            if not previous_adjustments <= current_adjustments:
                raise ApiError(503, "BILLING_RESTORE_REQUIRED", "费用核实记录早于保护记录，需先恢复台账")
            for old in previous["tables"].get("model_spends", []):
                current = current_spends[old["id"]]
                regressed = old["state"] in {"succeeded", "failed", "unknown"} and current["state"] in {"reserved", "running", "cancelled"}
                changed_settlement = old.get("charged_micro") is not None and old["charged_micro"] != current.get("charged_micro") and old["id"] not in new_adjusted_spends
                if regressed or changed_settlement:
                    raise ApiError(503, "BILLING_RESTORE_REQUIRED", "费用状态或金额早于保护记录，未覆盖最新台账")
        value = {"format": "careerpilot-billing-v1", "updatedAt": now_utc().isoformat(), "tables": data}
        value["sha256"] = hashlib.sha256(encoded(value)).hexdigest()
        atomic_json(root_for(settings) / "billing-protection.json", value)
        return value


def checkpointed(*, required=False):
    def decorate(method):
        @wraps(method)
        def wrapped(self, *args, **kwargs):
            result = method(self, *args, **kwargs)
            try:
                checkpoint_billing(self.engine, self.settings)
            except Exception as error:
                if required:
                    if isinstance(error, ApiError):
                        raise
                    raise ApiError(503, "BILLING_PROTECTION_FAILED", "费用保护记录未就绪，未继续发起模型调用") from None
                logger.error("billing_checkpoint_failed action=%s", method.__name__)
            return result
        return wrapped
    return decorate
