from collections.abc import Generator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings
from app.errors import ApiError


class Base(DeclarativeBase):
    pass


def make_engine(settings: Settings) -> Engine | None:
    if not settings.database_url:
        return None
    url = settings.database_url.get_secret_value()
    kwargs = {"pool_pre_ping": True, "hide_parameters": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


def session_factory(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    factory = request.app.state.session_factory
    if factory is None:
        raise ApiError(503, "DATABASE_NOT_CONFIGURED", "数据库尚未配置")
    with factory() as db:
        db.info["settings"] = request.app.state.settings
        try:
            yield db
        except Exception:
            db.rollback()
            raise


def fresh_authorization(db):
    """Locking current reads check writes against revocations committed in flight."""
    session_id = db.info.get("protected_session_id")
    user_id = db.info.get("protected_user_id")
    if not session_id:
        return
    from sqlalchemy import select

    from app.models import AuthSession, User, now_utc
    user = db.execute(select(User.enabled, User.closed_at).where(User.id == user_id).with_for_update()).first()
    auth = db.execute(select(AuthSession.revoked_at, AuthSession.expires_at, AuthSession.user_id)
                      .where(AuthSession.id == session_id).with_for_update()).first()
    if not user or not user.enabled or user.closed_at or not auth or auth.user_id != user_id or auth.revoked_at or auth.expires_at <= now_utc():
        raise ApiError(401, "SESSION_EXPIRED", "登录已失效，未接受本次操作，请重新登录")


@event.listens_for(Session, "before_commit")
def protect_inflight_writes(db):
    if not db.info.get("allow_authorization_change"):
        fresh_authorization(db)

