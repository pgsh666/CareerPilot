import hashlib
import hmac
import secrets

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.config import Settings
from app.errors import ApiError

password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


def require_secret(settings: Settings) -> str:
    if not settings.secret_key:
        raise ApiError(503, "AUTH_NOT_CONFIGURED", "认证密钥尚未配置")
    return settings.secret_key.get_secret_value()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def keyed_digest(settings: Settings, value: str) -> str:
    return hmac.new(require_secret(settings).encode(), value.encode(), hashlib.sha256).hexdigest()


def csrf_for_token(settings: Settings, token: str) -> str:
    return keyed_digest(settings, "csrf:" + token)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return password_hasher.verify(password, stored_hash)
    except (UnknownHashError, ValueError):
        return False

