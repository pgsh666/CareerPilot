from datetime import timedelta

import pytest
from conftest import PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import AuthSession, RateBucket, User, VerificationCode, now_utc
from app.security import digest, verify_password


def test_unconfigured_health_is_honest():
    secret = "never-log-this-short-key"
    with pytest.raises(ValueError) as error:
        Settings(_env_file=None, environment="test", database_url=None, secret_key=secret)
    assert secret not in str(error.value)
    app = create_app(Settings(_env_file=None, environment="test", database_url=None,
                              secret_key=None, allowed_hosts=["testserver"]))
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        response = client.post("/api/v1/auth/login", json={"email": "x@example.org", "password": PASSWORD})
        assert response.status_code == 503
        assert "request_id" in response.json()["error"]


def test_registered_account_verified_and_password_hashed(h):
    account = h.register()
    assert account["role"] == "user" and account["email_verified"]
    user = h.user()
    assert user.password_hash.startswith("$argon2")
    assert verify_password(PASSWORD, user.password_hash)
    assert PASSWORD not in str(account)
    assert h.client.get("/health/ready").status_code == 200


def test_email_normalized_and_resend_throttled(h):
    body = {"email": "Candidate@Example.ORG", "purpose": "register"}
    response = h.client.post("/api/v1/auth/codes", json=body)
    assert response.status_code == 202
    assert h.mailer.messages[0][0] == "candidate@example.org"
    assert h.mailer.messages[0][2].isdigit() and len(h.mailer.messages[0][2]) == 6
    assert "code" not in response.json()
    assert h.client.post("/api/v1/auth/codes", json=body).status_code == 429


def test_code_is_single_use(h):
    h.register()
    body = {"email": "candidate@example.org", "code": h.mailer.code("candidate@example.org"),
            "password": PASSWORD, "confirmation": PASSWORD}
    assert h.client.post("/api/v1/auth/register", json=body).status_code == 400
    with h.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_wrong_attempts_persist_and_lock_code(h):
    email = "candidate@example.org"
    h.client.post("/api/v1/auth/codes", json={"email": email, "purpose": "register"})
    code = h.mailer.code(email)
    wrong = "111111" if code != "111111" else "222222"
    body = {"email": email, "password": PASSWORD, "confirmation": PASSWORD, "code": wrong}
    for _ in range(5):
        assert h.client.post("/api/v1/auth/register", json=body).status_code == 400
    body["code"] = code
    assert h.client.post("/api/v1/auth/register", json=body).status_code == 400
    with h.app.state.session_factory() as db:
        assert db.scalar(select(VerificationCode)).attempts == 5


def test_expired_code_rejected(h):
    email = "candidate@example.org"
    h.client.post("/api/v1/auth/codes", json={"email": email, "purpose": "register"})
    with h.app.state.session_factory() as db:
        db.scalar(select(VerificationCode)).expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
    response = h.client.post("/api/v1/auth/register", json={
        "email": email, "code": h.mailer.code(email), "password": PASSWORD, "confirmation": PASSWORD,
    })
    assert response.status_code == 400


def test_resend_invalidates_prior_record(h):
    email = "candidate@example.org"
    body = {"email": email, "purpose": "register"}
    h.client.post("/api/v1/auth/codes", json=body)
    with h.app.state.session_factory() as db:
        for bucket in db.scalars(select(RateBucket)):
            bucket.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
    assert h.client.post("/api/v1/auth/codes", json=body).status_code == 202
    with h.app.state.session_factory() as db:
        codes = list(db.scalars(select(VerificationCode)))
        assert len(codes) == 2
        assert sum(c.used_at is None for c in codes) == 1


def test_failed_email_does_not_claim_success_or_create_code(h):
    h.mailer.fail = True
    response = h.client.post("/api/v1/auth/codes", json={"email": "x@example.org", "purpose": "register"})
    assert response.status_code == 503
    with h.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(VerificationCode)) == 0


def test_code_purpose_cannot_be_substituted(h):
    h.register()
    email = "candidate@example.org"
    h.client.post("/api/v1/auth/codes", json={"email": email, "purpose": "password_reset"})
    response = h.client.post("/api/v1/auth/register", json={
        "email": "new@example.org", "code": h.mailer.code(email, "password_reset"),
        "password": PASSWORD, "confirmation": PASSWORD,
    })
    assert response.status_code == 400
    assert h.user("new@example.org") is None


def test_login_cookie_and_server_session_security(h):
    h.register()
    response = h.client.post("/api/v1/auth/login", json={"email": "candidate@example.org", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=604800" in cookie
    raw = h.client.cookies.get("careerpilot_session")
    with h.app.state.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session.token_hash == digest(raw) and session.token_hash != raw
        assert session.expires_at > now_utc() + timedelta(days=6)
    assert h.client.get("/api/v1/auth/me").json()["csrf_token"] == response.json()["csrf_token"]


def test_logout_revokes_token_even_if_cookie_is_replayed(h):
    h.register()
    headers = h.login()
    raw = h.client.cookies.get("careerpilot_session")
    assert h.client.post("/api/v1/auth/logout").status_code == 403
    assert h.client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    h.client.cookies.set("careerpilot_session", raw)
    assert h.client.get("/api/v1/auth/me").status_code == 401


def test_profile_validation_and_account_isolation(h):
    first = h.register()
    headers = h.login()
    assert h.client.patch("/api/v1/account/profile", headers=headers, json={"name": "   "}).status_code == 422
    response = h.client.patch("/api/v1/account/profile", headers=headers,
                              json={"name": "  用户甲  ", "avatar": "star"})
    assert response.status_code == 200 and response.json()["account"]["name"] == "用户甲"
    h.client.post("/api/v1/auth/logout", headers=headers)
    second = h.register("another@example.org")
    h.login("another@example.org")
    assert second["id"] != first["id"]
    assert h.client.get("/api/v1/auth/me").json()["account"]["avatar"] == "default"
    assert h.user().name == "用户甲"


def test_role_mass_assignment_and_admin_auth_enforced(h):
    h.register()
    headers = h.login()
    assert h.client.patch("/api/v1/account/profile", headers=headers, json={"role": "admin"}).status_code == 422
    assert h.client.get("/api/v1/admin/access").status_code == 403
    h.make_admin()
    headers = h.login("admin@example.org")
    assert h.client.get("/api/v1/admin/access").status_code == 200
    assert h.client.patch("/api/v1/account/profile", headers=headers, json={"name": "changed"}).status_code == 403


def test_disabled_account_rejected_on_existing_session(h):
    h.register()
    h.login()
    with h.app.state.session_factory() as db:
        db.scalar(select(User)).enabled = False
        db.commit()
    assert h.client.get("/api/v1/auth/me").status_code == 403
    response = h.client.post("/api/v1/auth/login", json={"email": "candidate@example.org", "password": PASSWORD})
    assert response.status_code == 403


def test_password_reset_revokes_prior_sessions(h):
    h.register()
    h.login()
    email, new_password = "candidate@example.org", "Changed-password-2026!"
    h.client.post("/api/v1/auth/codes", json={"email": email, "purpose": "password_reset"})
    response = h.client.post("/api/v1/auth/password-reset", json={
        "email": email, "code": h.mailer.code(email, "password_reset"),
        "password": new_password, "confirmation": new_password,
    })
    assert response.status_code == 200
    assert h.client.get("/api/v1/auth/me").status_code == 401
    assert h.client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    h.login(password=new_password)


def test_password_change_requires_current_password(h):
    h.register()
    headers = h.login()
    body = {"current_password": "wrong", "password": "A-new-password-2026!", "confirmation": "A-new-password-2026!"}
    assert h.client.post("/api/v1/account/password", headers=headers, json=body).status_code == 400
    body["current_password"] = PASSWORD
    assert h.client.post("/api/v1/account/password", headers=headers, json=body).status_code == 200
    assert h.client.get("/api/v1/auth/me").status_code == 401


def test_email_change_code_bound_to_requesting_account(h):
    h.register()
    first_headers = h.login()
    target = "replacement@example.org"
    assert h.client.post("/api/v1/account/email/codes", headers=first_headers, json={"email": target}).status_code == 202
    code = h.mailer.code(target, "email_change")
    h.register("another@example.org")
    second_headers = h.login("another@example.org")
    assert h.client.post("/api/v1/account/email", headers=second_headers, json={"email": target, "code": code}).status_code == 400
    first_headers = h.login()
    assert h.client.post("/api/v1/account/email", headers=first_headers, json={"email": target, "code": code}).status_code == 200
    assert h.client.get("/api/v1/auth/me").status_code == 401
    h.login(target)
    assert h.user(target).email_verified


def test_cross_origin_write_and_missing_csrf_rejected(h):
    h.register()
    headers = h.login()
    assert h.client.patch("/api/v1/account/profile", json={"name": "blocked"}).status_code == 403
    headers["Origin"] = "https://untrusted.example.org"
    assert h.client.patch("/api/v1/account/profile", headers=headers, json={"name": "blocked"}).status_code == 403
    assert h.user().name != "blocked"
    # Same-origin API documentation must work without adding its URL to CORS origins.
    headers["Origin"] = "http://testserver"
    assert h.client.patch("/api/v1/account/profile", headers=headers, json={"name": "same-origin"}).status_code == 200


def test_login_attempts_limited(h):
    body = {"email": "unknown@example.org", "password": PASSWORD}
    for _ in range(10):
        assert h.client.post("/api/v1/auth/login", json=body).status_code == 401
    assert h.client.post("/api/v1/auth/login", json=body).status_code == 429


def test_expired_session_rejected(h):
    h.register()
    h.login()
    with h.app.state.session_factory() as db:
        db.scalar(select(AuthSession)).expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
    assert h.client.get("/api/v1/auth/me").status_code == 401


def test_validation_error_does_not_echo_secrets(h):
    secret = "do-not-echo-this-password"
    response = h.client.post("/api/v1/auth/register", json={
        "email": "candidate@example.org", "code": "123456", "password": secret,
        "confirmation": "different-secret",
    })
    assert response.status_code == 422
    assert secret not in response.text and "123456" not in response.text
    assert response.headers.get("x-request-id")


@pytest.mark.parametrize("email", ["user@example.com", "admin@example.com"])
def test_public_preview_credentials_are_not_real_accounts(h, email):
    assert h.client.post("/api/v1/auth/login", json={"email": email, "password": "Pilot@2026"}).status_code == 401
