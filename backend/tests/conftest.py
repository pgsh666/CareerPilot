from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import Base
from app.errors import ApiError
from app.main import create_app
from app.models import User
from app.security import password_hasher

PASSWORD = "Pilot-test-2026!"


class CaptureMailer:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send_code(self, email, purpose, code):
        if self.fail:
            raise ApiError(503, "MAIL_UNAVAILABLE", "验证码发送失败", retryable=True)
        self.messages.append((email, purpose, code))

    def code(self, email, purpose="register"):
        return next(code for address, kind, code in reversed(self.messages)
                    if address == email and kind == purpose)


@dataclass
class Harness:
    app: object
    client: TestClient
    mailer: CaptureMailer

    def register(self, email="candidate@example.org"):
        sent = self.client.post("/api/v1/auth/codes", json={"email": email, "purpose": "register"})
        assert sent.status_code == 202, sent.text
        code = self.mailer.code(email)
        response = self.client.post("/api/v1/auth/register", json={
            "email": email, "code": code, "password": PASSWORD, "confirmation": PASSWORD,
        })
        assert response.status_code == 201, response.text
        return response.json()["account"]

    def login(self, email="candidate@example.org", password=PASSWORD):
        response = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    def user(self, email="candidate@example.org"):
        with self.app.state.session_factory() as db:
            return db.scalar(select(User).where(User.email == email))

    def make_admin(self, email="admin@example.org"):
        with self.app.state.session_factory() as db:
            db.add(User(email=email, name="管理员", role="admin", email_verified=True,
                        password_hash=password_hasher.hash(PASSWORD)))
            db.commit()


@pytest.fixture
def h(tmp_path):
    settings = Settings(
        _env_file=None, environment="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        secret_key="test-only-secret-that-is-long-enough-for-hmac",
        allowed_hosts=["testserver"], allowed_origins=["https://ui.example.org"],
        material_directory=tmp_path / "private-materials",
        speech_temporary_directory=tmp_path / "speech-tmp",
    )
    mailer = CaptureMailer()
    app = create_app(settings, mailer=mailer)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        yield Harness(app, client, mailer)
    app.state.engine.dispose()

