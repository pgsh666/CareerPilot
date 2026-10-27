from datetime import timedelta

from app.errors import ApiError
from app.models import now_utc

LEASE_SECONDS = 30


def writable(row, lease, session_id, now=None):
    now = now or now_utc()
    return bool(row.status == "active" and lease and row.writer_lease == lease
                and row.writer_session_id == session_id and row.writer_seen_at
                and now - row.writer_seen_at < timedelta(seconds=LEASE_SECONDS))


def require_writer(row, lease, session_id):
    now = now_utc()
    if not writable(row, lease, session_id, now):
        raise ApiError(409, "TRAINING_READ_ONLY", "本页当前只读，请确认接管作答后再操作；已保存内容不会被覆盖")
    row.writer_seen_at = now


def acquire(row, body, session_id):
    now = now_utc()
    same = row.writer_lease == body.lease and row.writer_session_id == session_id
    if body.release:
        if same:
            row.writer_lease = row.writer_session_id = row.writer_seen_at = None
            row.activity_running = False
        return {"writable": False, "expiresIn": LEASE_SECONDS}
    alive = bool(row.writer_lease and row.writer_seen_at
                 and now - row.writer_seen_at < timedelta(seconds=LEASE_SECONDS))
    if row.status != "active" or (alive and not same and not body.takeover):
        return {"writable": False, "expiresIn": LEASE_SECONDS}
    if not same:
        row.activity_running = False
        row.activity_at = None
    row.writer_lease, row.writer_session_id, row.writer_seen_at = body.lease, session_id, now
    return {"writable": True, "expiresIn": LEASE_SECONDS}
