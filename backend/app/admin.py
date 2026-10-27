from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select

from app.auth import Admin, AuthContext, Db, Protected, admin_context, revoke_sessions
from app.errors import ApiError
from app.models import AuthSession, Training, User, now_utc

router = APIRouter(prefix="/api/v1/admin", tags=["administration"])


def protected_admin(context: Protected):
    return admin_context(context)


AdminWrite = Annotated[AuthContext, Depends(protected_admin)]


class StatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    enabled: bool


def metadata(db, user, actor):
    last_login = db.scalar(select(func.max(AuthSession.created_at)).where(AuthSession.user_id == user.id))
    return {"id": user.id, "name": user.name, "email": user.former_email or user.email, "role": user.role,
            "enabled": user.enabled, "self": user.id == actor, "closed": user.closed_at is not None,
            "registeredAt": user.created_at.isoformat(timespec="seconds") + "Z",
            "lastLoginAt": last_login.isoformat(timespec="seconds") + "Z" if last_login else None,
            "interviews": db.scalar(select(func.count()).select_from(Training).where(Training.owner_id == user.id, Training.mode == "interview")),
            "practices": db.scalar(select(func.count()).select_from(Training).where(Training.owner_id == user.id, Training.mode == "practice"))}


@router.get("/users")
def list_users(db: Db, context: Admin, q: str = Query("", max_length=254),
               status: Literal["all", "enabled", "disabled"] = "all",
               role: Literal["all", "user", "admin"] = "all",
               offset: int = Query(0, ge=0), limit: int = Query(4, ge=1, le=100)):
    filters = []
    if q.strip():
        filters.append(or_(User.name.contains(q.strip(), autoescape=True),
                           User.email.contains(q.strip(), autoescape=True),
                           User.former_email.contains(q.strip(), autoescape=True)))
    if status != "all":
        filters.append(User.enabled == (status == "enabled"))
    if role != "all":
        filters.append(User.role == role)
    total = db.scalar(select(func.count()).select_from(User).where(*filters))
    account_count = db.scalar(select(func.count()).select_from(User).where(User.closed_at.is_(None)))
    rows = db.scalars(select(User).where(*filters).order_by(User.created_at.desc(), User.id)
                      .offset(offset).limit(limit))
    return {"items": [metadata(db, user, context.user.id) for user in rows],
            "total": total, "accountCount": account_count}


@router.get("/users/{user_id}")
def read_user(user_id: str, db: Db, context: Admin):
    user = db.get(User, user_id)
    if not user:
        raise ApiError(404, "USER_NOT_FOUND", "账号不存在")
    return {"user": metadata(db, user, context.user.id)}


@router.patch("/users/{user_id}/status")
def set_status(user_id: str, body: StatusInput, db: Db, context: AdminWrite):
    locked = list(db.scalars(select(User).where(User.id.in_([user_id, context.user.id]))
                             .order_by(User.id).with_for_update()
                             .execution_options(populate_existing=True)))
    actor = next((u for u in locked if u.id == context.user.id), None)
    if not actor or not actor.enabled:
        raise ApiError(403, "ACCOUNT_UNAVAILABLE", "当前账号不可用")
    user = next((u for u in locked if u.id == user_id), None)
    if not user:
        raise ApiError(404, "USER_NOT_FOUND", "账号不存在")
    if user.closed_at:
        raise ApiError(409, "ACCOUNT_PERMANENTLY_CLOSED", "账号已永久注销，不能通过启用恢复")
    if user.id == context.user.id:
        raise ApiError(409, "CANNOT_DISABLE_SELF", "不能更改当前管理员的启停状态")
    if user.enabled != body.enabled:
        if not body.enabled:
            revoke_sessions(db, user.id)
        from app.control_journal import record
        record(db.info["settings"], "account_status", user.id, enabled=body.enabled)
        user.enabled, user.updated_at = body.enabled, now_utc()
        db.commit()
    return {"user": metadata(db, user, context.user.id)}
