"""Temporary local browser-test accounts, addressed by exact generated emails only."""
import json
import re
import secrets
import sys
from datetime import timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / ".deps")]

from sqlalchemy import delete, or_, select, update  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import make_engine, session_factory  # noqa: E402
from app.models import (  # noqa: E402
    AuthSession,
    AvatarImage,
    GenerationJob,
    Material,
    MaterialFile,
    MaterialVersion,
    ModelSpend,
    PracticeTask,
    RateBucket,
    SpeechTranscript,
    Training,
    TrainingAnswer,
    TrainingQuestion,
    TrainingSlot,
    User,
    VerificationCode,
    now_utc,
)
from app.security import digest, password_hasher  # noqa: E402

PATTERN = re.compile(r"^browser-auth-[0-9a-f]{32}-(a|b|changed)@example\.org$")


def main():
    payload = json.load(sys.stdin)
    emails = payload.get("emails", [payload.get("email", "")])
    if not isinstance(emails, list) or not 1 <= len(emails) <= 30:
        raise ValueError("Invalid test email list")
    if not all(isinstance(email, str) and PATTERN.fullmatch(email) for email in emails):
        raise ValueError("Only exact synthetic browser-check accounts are accepted")
    settings = Settings()
    if not settings.database_url:
        raise ValueError("Database is not configured")
    url = make_url(settings.database_url.get_secret_value())
    if (settings.environment != "development" or url.host not in {"127.0.0.1", "localhost"}
            or not str(url.database).startswith("careerpilot_app")):
        raise ValueError("Fixtures only support the isolated local development database")
    engine = make_engine(settings)
    files_to_remove = []
    try:
        with session_factory(engine).begin() as db:
            action = payload.get("action")
            if action == "prepare":
                if len(emails) != 1 or payload.get("role", "user") not in {"user", "admin"}:
                    raise ValueError("Invalid fixture request")
                if db.scalar(select(User).where(User.email == emails[0])):
                    raise ValueError("Synthetic test account already exists; it was not overwritten")
                password = secrets.token_urlsafe(24)
                name = payload.get("name", "浏览器联调")
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 24:
                    raise ValueError("Invalid test display name")
                user = User(email=emails[0], name=name.strip(), role=payload.get("role", "user"),
                            email_verified=True, password_hash=password_hasher.hash(password))
                db.add(user)
                db.flush()
                result = {"id": user.id, "email": user.email, "password": password, "name": user.name}
            elif action == "expire":
                ids = list(db.scalars(select(User.id).where(or_(User.email.in_(emails), User.former_email.in_(emails)))))
                if ids:
                    db.execute(update(AuthSession).where(AuthSession.user_id.in_(ids))
                               .values(expires_at=now_utc() - timedelta(seconds=1)))
                result = {"expired": len(ids)}
            elif action == "cleanup":
                ids = list(db.scalars(select(User.id).where(or_(User.email.in_(emails), User.former_email.in_(emails)))))
                if ids:
                    db.execute(delete(AvatarImage).where(AvatarImage.owner_id.in_(ids)))
                    training_ids = list(db.scalars(select(Training.id).where(Training.owner_id.in_(ids))))
                    db.execute(delete(GenerationJob).where(GenerationJob.owner_id.in_(ids)))
                    db.execute(delete(PracticeTask).where(PracticeTask.owner_id.in_(ids)))
                    if training_ids:
                        question_ids = list(db.scalars(select(TrainingQuestion.id).where(TrainingQuestion.training_id.in_(training_ids))))
                        db.execute(delete(TrainingAnswer).where(TrainingAnswer.training_id.in_(training_ids)))
                        if question_ids:
                            db.execute(delete(SpeechTranscript).where(SpeechTranscript.question_id.in_(question_ids)))
                        db.execute(delete(TrainingQuestion).where(TrainingQuestion.training_id.in_(training_ids)))
                    db.execute(delete(TrainingSlot).where(TrainingSlot.owner_id.in_(ids)))
                    if training_ids:
                        db.execute(delete(Training).where(Training.id.in_(training_ids)))
                    # Never erase actual charges or budget counters when removing synthetic actors.
                    db.execute(update(ModelSpend).where(ModelSpend.owner_id.in_(ids)).values(owner_id=None, result=None))
                    material_ids = list(db.scalars(select(Material.id).where(Material.owner_id.in_(ids))))
                    file_ids = list(db.scalars(select(MaterialFile.id).where(MaterialFile.owner_id.in_(ids))))
                    root = settings.material_directory.resolve()
                    if not root.is_relative_to((BACKEND / "data").resolve()):
                        raise ValueError("Test file cleanup must stay inside backend/data")
                    files_to_remove = [root / file_id for file_id in file_ids]
                    if not all(path.resolve().parent == root for path in files_to_remove):
                        raise ValueError("Invalid fixture file path")
                    if material_ids:
                        db.execute(delete(MaterialVersion).where(MaterialVersion.material_id.in_(material_ids)))
                        db.execute(delete(Material).where(Material.id.in_(material_ids)))
                    db.execute(delete(MaterialFile).where(MaterialFile.owner_id.in_(ids)))
                    db.execute(delete(AuthSession).where(AuthSession.user_id.in_(ids)))
                    db.execute(delete(VerificationCode).where(VerificationCode.owner_id.in_(ids)))
                db.execute(delete(VerificationCode).where(VerificationCode.email.in_(emails)))
                if ids:
                    db.execute(delete(User).where(User.id.in_(ids)))
                keys = [digest(f"mail:{purpose}:{email}") for email in emails
                        for purpose in ("register", "password_reset", "email_change")]
                keys += [digest(f"login-email:{email}") for email in emails]
                db.execute(delete(RateBucket).where(RateBucket.key.in_(keys)))
                result = {"removed": len(ids)}
            else:
                raise ValueError("Unsupported fixture action")
        for path in files_to_remove:
            path.unlink(missing_ok=True)
        # Returned to the test runner's private pipe; never logged to tool output or reports.
        print(json.dumps(result, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": type(error).__name__}))
        raise SystemExit(1) from None
