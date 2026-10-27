import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import fresh_authorization, get_db
from app.errors import ApiError
from app.models import (
    AuthSession,
    AvatarImage,
    GenerationJob,
    RateBucket,
    User,
    VerificationCode,
    new_id,
    now_utc,
)
from app.schemas import (
    ChallengeInput,
    ChangePasswordInput,
    CloseAccountInput,
    EmailCodeInput,
    EmailInput,
    LoginInput,
    ProfileInput,
    RegisterInput,
)
from app.security import (
    csrf_for_token,
    digest,
    dummy_hash,
    keyed_digest,
    password_hasher,
    require_secret,
    verify_password,
)

router = APIRouter(prefix="/api/v1", tags=["accounts"])
Db = Annotated[Session, Depends(get_db)]


def settings_for(request: Request) -> Settings:
    return request.app.state.settings


Config = Annotated[Settings, Depends(settings_for)]


@dataclass
class AuthContext:
    user: User
    session: AuthSession
    csrf: str


def current_context(request: Request, db: Db, settings: Config) -> AuthContext:
    raw = request.cookies.get(settings.cookie_name, "")
    if not raw or len(raw) > 512:
        raise ApiError(401, "AUTH_REQUIRED", "请先登录")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == digest(raw)))
    if not session or session.revoked_at or session.expires_at <= now_utc():
        raise ApiError(401, "SESSION_EXPIRED", "登录已失效，请重新登录")
    user = db.get(User, session.user_id)
    if not user or not user.enabled or not user.email_verified or user.closed_at:
        raise ApiError(403, "ACCOUNT_UNAVAILABLE", "当前账号不可用")
    db.info["origin_session_id"] = session.id
    request.state.auth_session_id = session.id
    return AuthContext(user, session, csrf_for_token(settings, raw))


Current = Annotated[AuthContext, Depends(current_context)]


def csrf_context(request: Request, context: Current, db: Db) -> AuthContext:
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not hmac.compare_digest(digest(supplied), context.session.csrf_hash):
        raise ApiError(403, "CSRF_REQUIRED", "请求验证失败，请刷新后重试")
    db.info["protected_session_id"] = context.session.id
    db.info["protected_user_id"] = context.user.id
    return context


Protected = Annotated[AuthContext, Depends(csrf_context)]


def admin_context(context: Current) -> AuthContext:
    if context.user.role != "admin":
        raise ApiError(403, "ADMIN_REQUIRED", "需要管理员权限")
    return context


Admin = Annotated[AuthContext, Depends(admin_context)]


def user_payload(user: User):
    return {
        "id": user.id, "email": user.email, "name": user.name,
        "avatar": "admin" if user.role == "admin" else user.avatar,
        "avatarUrl": "/api/v1/account/avatar/" + user.avatar if user.role != "admin" and user.avatar.startswith("upload_") else None,
        "role": user.role, "enabled": user.enabled, "email_verified": user.email_verified,
    }


def hit_limit(db: Session, key: str, limit: int, seconds: int):
    key = digest(key)
    bucket = db.scalar(select(RateBucket).where(RateBucket.key == key).with_for_update())
    now = now_utc()
    if not bucket:
        db.add(RateBucket(key=key, count=1, expires_at=now + timedelta(seconds=seconds)))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Another request created this bucket; lock and increment that row.
            existing = db.scalar(select(RateBucket).where(RateBucket.key == key).with_for_update())
            if not existing:
                raise ApiError(429, "RATE_LIMITED", "操作过于频繁，请稍后重试") from None
            if existing.expires_at <= now:
                existing.count, existing.expires_at = 0, now + timedelta(seconds=seconds)
            if existing.count >= limit:
                raise ApiError(429, "RATE_LIMITED", "操作过于频繁，请稍后重试") from None
            existing.count += 1
            db.commit()
        return
    if bucket.expires_at <= now:
        bucket.count, bucket.expires_at = 0, now + timedelta(seconds=seconds)
    if bucket.count >= limit:
        raise ApiError(429, "RATE_LIMITED", "操作过于频繁，请稍后重试")
    bucket.count += 1
    db.commit()


def code_digest(settings: Settings, row: VerificationCode, code: str):
    return keyed_digest(settings, f"otp:{row.id}:{row.email}:{row.purpose}:{row.owner_id or ''}:{code}")


def issue_code(request: Request, db: Session, settings: Settings, email: str, purpose: str, owner_id=None):
    require_secret(settings)
    host = request.client.host if request.client else "unknown"
    hit_limit(db, f"mail-ip:{host}", 20, 3600)
    hit_limit(db, f"mail:{purpose}:{email}", 1, settings.code_resend_seconds)
    user = db.scalar(select(User).where(User.email == email))
    eligible = (purpose == "register" and user is None) or (
        purpose == "password_reset" and user is not None and user.enabled
    ) or (purpose == "email_change" and user is None and owner_id is not None)
    if not eligible:
        return {"message": "如该邮箱符合本次操作条件，验证码将发送至邮箱"}
    now = now_utc()
    row = VerificationCode(
        id=new_id(), email=email, purpose=purpose, owner_id=owner_id,
        created_at=now, expires_at=now + timedelta(seconds=settings.code_ttl_seconds),
    )
    code = "".join(secrets.choice("0123456789") for _ in range(settings.code_digits))
    row.code_hash = code_digest(settings, row, code)
    # Old codes are invalidated atomically with the replacement, only after SMTP accepts it.
    request.app.state.mailer.send_code(email, purpose, code)
    db.execute(update(VerificationCode).where(
        VerificationCode.email == email, VerificationCode.purpose == purpose,
        VerificationCode.owner_id == owner_id, VerificationCode.used_at.is_(None),
    ).values(used_at=now))
    db.add(row)
    db.commit()
    return {"message": "如该邮箱符合本次操作条件，验证码将发送至邮箱"}


def consume_code(db: Session, settings: Settings, email: str, purpose: str, code: str, owner_id=None):
    row = db.scalar(select(VerificationCode).where(
        VerificationCode.email == email, VerificationCode.purpose == purpose,
        VerificationCode.owner_id == owner_id, VerificationCode.used_at.is_(None),
    ).order_by(VerificationCode.created_at.desc(), VerificationCode.id.desc()).with_for_update())
    now = now_utc()
    if not row or row.expires_at <= now or row.attempts >= settings.code_max_attempts:
        raise ApiError(400, "CODE_INVALID", "验证码错误或已失效")
    row.attempts += 1
    if not hmac.compare_digest(code_digest(settings, row, code), row.code_hash):
        # Failed attempts must persist even though the business operation fails.
        db.commit()
        raise ApiError(400, "CODE_INVALID", "验证码错误或已失效")
    row.used_at = now
    return row


def revoke_sessions(db: Session, user_id: str):
    if db.info.get("protected_user_id") == user_id:
        fresh_authorization(db)
        db.info["allow_authorization_change"] = True
    from app.training_service import interrupt_active
    interrupt_active(db, user_id, "authorization_changed")
    db.execute(update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    ).values(revoked_at=now_utc()))
    db.execute(update(GenerationJob).where(GenerationJob.owner_id == user_id,
               GenerationJob.state.in_(["queued", "ready"])).values(state="paused"))


@router.post("/auth/codes", status_code=202)
def send_code(body: ChallengeInput, request: Request, db: Db, settings: Config):
    return issue_code(request, db, settings, str(body.email), body.purpose)


@router.post("/auth/register", status_code=201)
def register(body: RegisterInput, db: Db, settings: Config):
    consume_code(db, settings, str(body.email), "register", body.code)
    user = User(
        email=str(body.email), password_hash=password_hasher.hash(body.password.get_secret_value()),
        name=str(body.email).split("@")[0][:24], role="user", email_verified=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "ACCOUNT_CONFLICT", "该邮箱无法用于本次注册") from None
    return {"account": user_payload(user)}


@router.post("/auth/login")
def login(body: LoginInput, request: Request, response: Response, db: Db, settings: Config):
    require_secret(settings)
    host = request.client.host if request.client else "unknown"
    hit_limit(db, f"login-ip:{host}", settings.login_limit * 3, settings.login_window_seconds)
    hit_limit(db, f"login-email:{body.email}", settings.login_limit, settings.login_window_seconds)
    user = db.scalar(select(User).where(User.email == str(body.email)))
    valid = verify_password(body.password.get_secret_value(), user.password_hash if user else dummy_hash)
    if not valid or not user:
        raise ApiError(401, "LOGIN_INVALID", "邮箱或密码不正确")
    if not user.enabled or not user.email_verified or user.closed_at:
        raise ApiError(403, "ACCOUNT_UNAVAILABLE", "当前账号不可用")
    # Rotate a previous browser session rather than leaving its stolen token alive.
    previous = request.cookies.get(settings.cookie_name)
    if previous:
        db.execute(update(AuthSession).where(
            AuthSession.token_hash == digest(previous), AuthSession.revoked_at.is_(None)
        ).values(revoked_at=now_utc()))
    token = secrets.token_urlsafe(48)
    csrf = csrf_for_token(settings, token)
    now = now_utc()
    session = AuthSession(
        user_id=user.id, token_hash=digest(token), csrf_hash=digest(csrf),
        expires_at=now + timedelta(days=settings.session_days),
    )
    db.add(session)
    db.commit()
    response.set_cookie(
        settings.cookie_name, token, max_age=settings.session_days * 86400,
        httponly=True, secure=settings.cookie_secure, samesite="lax", path="/",
    )
    return {"account": user_payload(user), "csrf_token": csrf,
            "expires_at": session.expires_at.isoformat() + "Z"}


@router.get("/auth/me")
def me(context: Current):
    return {"account": user_payload(context.user), "csrf_token": context.csrf}


@router.post("/auth/logout")
def logout(response: Response, db: Db, settings: Config, context: Protected):
    from app.training_service import interrupt_active
    fresh_authorization(db)
    interrupt_active(db, context.user.id)
    db.info["allow_authorization_change"] = True
    context.session.revoked_at = now_utc()
    db.execute(update(GenerationJob).where(GenerationJob.owner_id == context.user.id,
               GenerationJob.state.in_(["queued", "ready"]),
               (GenerationJob.auth_session_id == context.session.id) | GenerationJob.auth_session_id.is_(None))
               .values(state="paused"))
    db.commit()
    response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure,
                           httponly=True, samesite="lax")
    return {"message": "已退出登录"}


@router.post("/auth/password-reset")
def reset_password(body: RegisterInput, db: Db, settings: Config):
    consume_code(db, settings, str(body.email), "password_reset", body.code)
    user = db.scalar(select(User).where(User.email == str(body.email)).with_for_update())
    if not user or not user.enabled:
        raise ApiError(400, "CODE_INVALID", "验证码错误或已失效")
    revoke_sessions(db, user.id)
    user.password_hash = password_hasher.hash(body.password.get_secret_value())
    db.commit()
    return {"message": "密码已重置，请重新登录"}


@router.patch("/account/profile")
def update_profile(body: ProfileInput, db: Db, context: Protected):
    if context.user.role == "admin":
        raise ApiError(403, "PROFILE_NOT_AVAILABLE", "管理员不提供个人资料修改")
    from app.training_service import lock_owner
    user = lock_owner(db, context.user.id)
    if body.name is not None:
        user.name = body.name
    if body.avatar is not None:
        user.avatar = body.avatar
        db.execute(delete(AvatarImage).where(AvatarImage.owner_id == user.id))
    db.commit()
    return {"account": user_payload(user)}


@router.post("/account/password")
def change_password(body: ChangePasswordInput, response: Response, db: Db, settings: Config, context: Protected):
    if context.user.role == "admin":
        raise ApiError(403, "PASSWORD_NOT_AVAILABLE", "管理员不提供此密码修改入口")
    if not verify_password(body.current_password.get_secret_value(), context.user.password_hash):
        raise ApiError(400, "CURRENT_PASSWORD_INVALID", "当前密码不正确")
    revoke_sessions(db, context.user.id)
    context.user.password_hash = password_hasher.hash(body.password.get_secret_value())
    db.commit()
    response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure,
                           httponly=True, samesite="lax")
    return {"message": "密码已修改，请重新登录"}


@router.post("/account/email/codes", status_code=202)
def send_email_change(body: EmailInput, request: Request, db: Db, settings: Config, context: Protected):
    if context.user.role == "admin":
        raise ApiError(403, "PROFILE_NOT_AVAILABLE", "管理员不提供邮箱换绑入口")
    return issue_code(request, db, settings, str(body.email), "email_change", context.user.id)


@router.post("/account/email")
def change_email(body: EmailCodeInput, response: Response, db: Db, settings: Config, context: Protected):
    if context.user.role == "admin":
        raise ApiError(403, "PROFILE_NOT_AVAILABLE", "管理员不提供邮箱换绑入口")
    consume_code(db, settings, str(body.email), "email_change", body.code, context.user.id)
    revoke_sessions(db, context.user.id)
    context.user.email = str(body.email)
    context.user.email_verified = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "ACCOUNT_CONFLICT", "该邮箱无法用于本次换绑") from None
    response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure,
                           httponly=True, samesite="lax")
    return {"message": "邮箱已更新，请重新登录"}


@router.get("/admin/access", tags=["admin"])
def check_admin(context: Admin):
    # Foundation endpoint only; user management and training counts are separate work.
    return {"role": context.user.role}


@router.post("/account/close")
def close_account(body: CloseAccountInput, db: Db, context: Protected):
    from app.training_service import interrupt_active, lock_owner
    user = lock_owner(db, context.user.id)
    if user.role == "admin":
        raise ApiError(403, "CLOSURE_NOT_AVAILABLE", "管理员不提供此注销入口")
    if str(body.email) != user.email:
        raise ApiError(422, "CLOSURE_EMAIL_MISMATCH", "请输入当前账号邮箱确认注销")
    interrupt_active(db, user.id, "account_closed")
    revoke_sessions(db, user.id)
    db.execute(update(VerificationCode).where(VerificationCode.email == user.email,
                                            VerificationCode.used_at.is_(None)).values(used_at=now_utc()))
    from app.control_journal import record
    closed = now_utc()
    record(db.info["settings"], "account_closed", user.id, at=closed)
    user.former_email = user.email
    user.email = f"closed-{user.id}@closed.invalid"
    user.closed_at, user.enabled, user.updated_at = closed, False, closed
    db.commit()
    return {"message": "账号已永久关闭，个人数据自注销起保留30天后清理；同邮箱可注册全新账号。",
            "retentionPolicy": "closed_30_days", "purgeAfter": (closed + timedelta(days=30)).isoformat() + "Z"}
