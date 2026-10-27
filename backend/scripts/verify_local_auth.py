"""Real local HTTP/MySQL/Mailpit verification with exact synthetic-record cleanup."""
import json
import re
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / ".deps")]

import httpx  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import make_engine, session_factory  # noqa: E402
from app.models import AuthSession, RateBucket, User, VerificationCode  # noqa: E402
from app.security import digest  # noqa: E402

API = "http://127.0.0.1:8000"
MAIL = "http://127.0.0.1:8025"


class CheckFailed(Exception):
    pass


def main():
    settings = Settings()
    if not settings.database_url:
        raise SystemExit("Project database is not configured")
    url = make_url(settings.database_url.get_secret_value())
    if (
        settings.environment != "development"
        or url.host not in {"127.0.0.1", "localhost"}
        or not str(url.database).startswith("careerpilot_app")
        or settings.smtp_host not in {"127.0.0.1", "localhost"}
        or settings.smtp_port != 1025
    ):
        raise SystemExit("Verification only supports the isolated local development database and Mailpit")
    marker = uuid4().hex
    emails = [f"backend-check-{kind}-{marker}@example.org" for kind in ("a", "b", "changed")]
    password = secrets.token_urlsafe(24)
    new_password = secrets.token_urlsafe(24)
    last_password = secrets.token_urlsafe(24)
    checks = []
    message_ids = set()
    engine = make_engine(settings)
    sessions = session_factory(engine)
    report = {
        "started_at": datetime.now(UTC).isoformat(), "database": url.database,
        "api": API, "checks": checks, "status": "running",
    }
    clients = [httpx.Client(base_url=API, timeout=15, trust_env=False,
                           headers={"Origin": API}) for _ in range(2)]

    def expect(response, status, label):
        if response.status_code != status:
            raise CheckFailed(f"{label}: HTTP {response.status_code}, expected {status}")
        checks.append(label)
        return response.json()

    def check(condition, label):
        if not condition:
            raise CheckFailed(label)
        checks.append(label)

    def code_for(email):
        # Search only the unique recipient created by this run, never list the mailbox.
        with httpx.Client(timeout=5, trust_env=False) as mail:
            for _ in range(30):
                search = mail.get(f"{MAIL}/api/v1/search", params={"query": "to:" + email})
                if search.status_code != 200:
                    raise CheckFailed("Mailpit own-recipient search failed")
                for item in search.json().get("messages", []):
                    message_id = item["ID"]
                    response = mail.get(f"{MAIL}/api/v1/message/{message_id}")
                    if response.status_code != 200:
                        continue
                    message = response.json()
                    recipients = {address.get("Address", "").lower()
                                  for address in message.get("To", [])}
                    if email not in recipients:
                        continue
                    match = re.search(r"验证码[：:]\s*([0-9]{6})(?![0-9])", message.get("Text", ""))
                    if match:
                        message_ids.add(message_id)
                        return match.group(1)
                time.sleep(0.1)
        raise CheckFailed("Mailpit did not return the expected synthetic verification message")

    def send_code(client, email, purpose):
        expect(client.post("/api/v1/auth/codes", json={"email": email, "purpose": purpose}),
               202, "真实SMTP验证码发送：" + purpose)
        return code_for(email)

    def register(client, email):
        code = send_code(client, email, "register")
        data = expect(client.post("/api/v1/auth/register", json={
            "email": email, "code": code, "password": password, "confirmation": password,
        }), 201, "真实MySQL注册写入")
        return data["account"]["id"]

    def login(client, email, current_password):
        response = client.post("/api/v1/auth/login", json={"email": email, "password": current_password})
        data = expect(response, 200, "真实MySQL登录")
        check("HttpOnly" in response.headers.get("set-cookie", ""), "登录Cookie为HttpOnly")
        return {"X-CSRF-Token": data["csrf_token"]}

    try:
        first, second = clients
        expect(first.get("/health/live"), 200, "后端HTTP存活")
        expect(first.get("/health/ready"), 200, "真实数据库及迁移就绪")
        owner_a = register(first, emails[0])
        headers_a = login(first, emails[0], password)
        expect(first.patch("/api/v1/account/profile", json={"name": "拒绝无令牌写入"}),
               403, "CSRF缺失被拦截")
        response = expect(first.patch("/api/v1/account/profile", headers=headers_a,
                                     json={"name": "真实数据库联调甲", "avatar": "star"}),
                          200, "资料与中文字符写入")
        check(response["account"]["name"] == "真实数据库联调甲", "中文资料正确返回")
        owner_b = register(second, emails[1])
        headers_b = login(second, emails[1], password)
        data_b = expect(second.get("/api/v1/auth/me"), 200, "恢复账号B资料")
        check(owner_a != owner_b and data_b["account"]["name"] != "真实数据库联调甲",
              "两个账号资料隔离")
        expect(second.get("/api/v1/admin/access"), 403, "普通用户管理接口越权被拦截")
        expect(second.patch("/api/v1/account/profile", headers=headers_b, json={"role": "admin"}),
               422, "客户端角色赋值被拦截")
        with sessions() as db:
            user = db.get(User, owner_b)
            user.enabled = False
            db.commit()
        expect(second.get("/api/v1/auth/me"), 403, "停用账号已有登录受阻")
        with sessions() as db:
            user = db.get(User, owner_b)
            user.enabled, user.role = True, "admin"
            db.commit()
        expect(second.get("/api/v1/admin/access"), 200, "服务端角色鉴权生效")
        expect(second.patch("/api/v1/account/profile", headers=headers_b, json={"name": "不应修改"}),
               403, "管理员个人资料入口受限")
        code = send_code(first, emails[0], "password_reset")
        expect(first.post("/api/v1/auth/password-reset", json={
            "email": emails[0], "code": code, "password": new_password, "confirmation": new_password,
        }), 200, "真实邮件验证码重置密码")
        expect(first.get("/api/v1/auth/me"), 401, "重置密码后旧登录失效")
        expect(first.post("/api/v1/auth/login", json={"email": emails[0], "password": password}),
               401, "重置后旧密码失效")
        headers_a = login(first, emails[0], new_password)
        expect(first.post("/api/v1/account/email/codes", headers=headers_a,
                          json={"email": emails[2]}), 202, "真实SMTP换绑验证码发送")
        code = code_for(emails[2])
        expect(first.post("/api/v1/account/email", headers=headers_a,
                          json={"email": emails[2], "code": code}), 200, "换绑邮箱写入真实MySQL")
        expect(first.get("/api/v1/auth/me"), 401, "换绑后旧登录失效")
        headers_a = login(first, emails[2], new_password)
        data_a = expect(first.get("/api/v1/auth/me"), 200, "换绑后重新登录")
        check(data_a["account"]["id"] == owner_a and data_a["account"]["email"] == emails[2],
              "换绑保持账号ID及资料归属")
        expect(first.post("/api/v1/account/password", headers=headers_a, json={
            "current_password": new_password, "password": last_password, "confirmation": last_password,
        }), 200, "旧密码校验后修改密码")
        expect(first.get("/api/v1/auth/me"), 401, "修改密码后旧登录失效")
        headers_a = login(first, emails[2], last_password)
        raw_cookie = first.cookies.get(settings.cookie_name)
        expect(first.post("/api/v1/auth/logout", headers=headers_a), 200, "退出登录")
        expect(first.get("/api/v1/auth/me"), 401, "退出后受保护接口失效")
        first.cookies.set(settings.cookie_name, raw_cookie)
        expect(first.get("/api/v1/auth/me"), 401, "退出后重放旧Cookie仍被拒绝")
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc) if isinstance(exc, CheckFailed) else type(exc).__name__
    finally:
        for client in clients:
            client.close()
        try:
            with sessions.begin() as db:
                # Exact random emails/IDs only. Never clear tables or touch non-test users.
                ids = list(db.scalars(select(User.id).where(User.email.in_(emails))))
                if ids:
                    db.execute(delete(AuthSession).where(AuthSession.user_id.in_(ids)))
                    db.execute(delete(VerificationCode).where(VerificationCode.owner_id.in_(ids)))
                db.execute(delete(VerificationCode).where(VerificationCode.email.in_(emails)))
                if ids:
                    db.execute(delete(User).where(User.id.in_(ids)))
                own_keys = [digest(f"mail:{purpose}:{email}") for email in emails
                            for purpose in ("register", "password_reset", "email_change")]
                own_keys += [digest(f"login-email:{email}") for email in emails]
                db.execute(delete(RateBucket).where(RateBucket.key.in_(own_keys)))
            with sessions() as db:
                remains = db.scalar(select(User.id).where(User.email.in_(emails)))
                report["synthetic_users_cleaned"] = remains is None
                if remains:
                    report["status"] = "failed"
                    report["cleanup_error"] = "Synthetic user cleanup incomplete"
        except Exception as exc:
            report["status"] = "failed"
            report["cleanup_error"] = type(exc).__name__
        engine.dispose()
        report["local_test_messages"] = len(message_ids)
        report["finished_at"] = datetime.now(UTC).isoformat()
        folder = BACKEND.parent / "artifacts" / "backend-mysql-2026-10-25"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"], "checks": len(checks),
                          "synthetic_users_cleaned": report.get("synthetic_users_cleaned", False),
                          "report": str(folder / "report.json")}, ensure_ascii=False))
        if report["status"] != "passed":
            print("Verification did not pass: " + report.get("error", report.get("cleanup_error", "unknown")))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
