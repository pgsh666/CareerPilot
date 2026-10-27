"""Minimal revocation/deletion journal kept outside database restores. No email or content."""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from app.errors import ApiError
from app.models import new_id, now_utc

_lock = RLock()
_named_locks = {}


def root_for(settings):
    if settings.environment != "test":
        return settings.maintenance_directory.resolve()
    from sqlalchemy.engine import make_url
    if settings.database_url:
        url = make_url(settings.database_url.get_secret_value())
        if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
            return Path(url.database).resolve().parent / "maintenance"
    return (settings.material_directory.parent / "maintenance").resolve()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@contextmanager
def journal_lock(settings, name="journal"):
    root = root_for(settings)
    root.mkdir(parents=True, exist_ok=True)
    if name not in {"journal", "billing", "maintenance"}:
        raise ValueError("Invalid maintenance lock")
    with _lock:
        local_lock = _named_locks.setdefault(str(root / name), RLock())
    with local_lock, (root / (name + ".lock")).open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            for _ in range(100):
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise ApiError(503, "CONTROL_JOURNAL_BUSY", "维护记录正在写入，请稍后重试")
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield root / "controls.jsonl"
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def read_path(path):
    if not path.exists():
        return []
    rows, previous = [], ""
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            claimed = row.pop("hash")
            if row["previous"] != previous or hashlib.sha256(encoded(row)).hexdigest() != claimed:
                raise ValueError("hash")
            row["hash"] = claimed
            if row["kind"] not in {"account_closed", "account_status", "material_deleted"}:
                raise ValueError("kind")
        except (ValueError, KeyError, TypeError):
            raise ApiError(503, "CONTROL_JOURNAL_INVALID", "维护记录校验失败，未继续修改或恢复数据") from None
        rows.append(row)
        previous = claimed
    return rows


def load(settings, *, required=False):
    with journal_lock(settings) as path:
        if required and not path.exists():
            raise ApiError(409, "LATEST_CONTROLS_REQUIRED", "缺少最新注销/删除记录，不能直接开放恢复数据")
        return read_path(path)


def record(settings, kind, target, *, at=None, enabled=None):
    if kind not in {"account_closed", "account_status", "material_deleted"}:
        raise ValueError("Unknown control marker")
    stamp = (at or now_utc()).isoformat(timespec="microseconds")
    with journal_lock(settings) as path:
        rows = read_path(path)
        latest = next((r for r in reversed(rows) if r["kind"] == kind and r["target"] == target), None)
        if latest and (kind != "account_status" or latest.get("enabled") == enabled):
            return latest
        row = {"id": new_id(), "kind": kind, "target": target, "at": stamp,
               "previous": rows[-1]["hash"] if rows else ""}
        if kind == "account_status":
            row["enabled"] = bool(enabled)
        row["hash"] = hashlib.sha256(encoded(row)).hexdigest()
        with path.open("ab") as handle:
            handle.write(encoded(row) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return row


def initialize(settings):
    with journal_lock(settings) as path:
        if not path.exists():
            path.touch(exist_ok=False)
        read_path(path)
