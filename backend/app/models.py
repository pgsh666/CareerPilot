from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def now_utc() -> datetime:
    # MySQL DATETIME stores UTC without a timezone; API formatting adds Z explicitly.
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return str(uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    name: Mapped[str] = mapped_column(String(24), nullable=False)
    avatar: Mapped[str] = mapped_column(String(24), default="default", nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    former_email: Mapped[str | None] = mapped_column(String(254))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc, nullable=False
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class AvatarImage(Base):
    __tablename__ = "avatar_images"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    png_base64: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class VerificationCode(Base):
    __tablename__ = "verification_codes"
    __table_args__ = (
        Index("ix_verification_lookup", "email", "purpose", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class RateBucket(Base):
    __tablename__ = "rate_buckets"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MaterialFile(Base):
    __tablename__ = "material_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    file_type: Mapped[str] = mapped_column(String(8), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        UniqueConstraint("owner_id", "kind", "request_key", name="uq_material_request"),
        Index("ix_material_owner_kind_time", "owner_id", "kind", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_id: Mapped[str | None] = mapped_column(ForeignKey("material_files.id"))
    source: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql"), default="", nullable=False)
    fields: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    extracted_fields: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(180))
    parser_version: Mapped[str] = mapped_column(String(40), default="source-rules-v1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class MaterialVersion(Base):
    __tablename__ = "material_versions"
    __table_args__ = (UniqueConstraint("material_id", "number", name="uq_material_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id"), index=True, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class ModelBudget(Base):
    __tablename__ = "model_budgets"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    limit_micro: Mapped[int] = mapped_column(BigInteger, nullable=False)
    charged_micro: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    held_micro: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    sent_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pending_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_calls: Mapped[int | None] = mapped_column(Integer)


class ModelSpend(Base):
    __tablename__ = "model_spends"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    month_key: Mapped[str] = mapped_column(ForeignKey("model_budgets.key"), nullable=False)
    test_mode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="reserved", nullable=False)
    reserved_micro: Mapped[int] = mapped_column(BigInteger, nullable=False)
    charged_micro: Mapped[int | None] = mapped_column(BigInteger)
    fee_source: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    pricing: Mapped[dict] = mapped_column(JSON, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(48))
    result: Mapped[dict | None] = mapped_column(JSON)
    diagnostic: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class FeeAdjustment(Base):
    __tablename__ = "model_fee_adjustments"
    __table_args__ = (UniqueConstraint("spend_id", "evidence_ref", name="uq_fee_adjustment_evidence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    spend_id: Mapped[str] = mapped_column(ForeignKey("model_spends.id"), nullable=False, index=True)
    evidence_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_micro: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_amount_micro: Mapped[int | None] = mapped_column(BigInteger)
    previous_state: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_error_code: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class Training(Base):
    __tablename__ = "trainings"
    __table_args__ = (UniqueConstraint("owner_id", "request_key", name="uq_training_request"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    phase: Mapped[str] = mapped_column(String(20), default="preparing", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(40), default="rules_pending", nullable=False)
    scoring_snapshot: Mapped[dict | None] = mapped_column(JSON)
    writer_lease: Mapped[str | None] = mapped_column(String(36))
    writer_session_id: Mapped[str | None] = mapped_column(String(36))
    writer_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    current_question_id: Mapped[str | None] = mapped_column(String(36))
    active_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    activity_lease: Mapped[str | None] = mapped_column(String(36))
    activity_sequence: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    activity_at: Mapped[datetime | None] = mapped_column(DateTime)
    activity_running: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resume_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    job_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36))
    source_id: Mapped[str | None] = mapped_column(String(36))
    original_answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    feedback: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    report: Mapped[dict | None] = mapped_column(JSON)
    report_state: Mapped[str] = mapped_column(String(20), default="not_requested", nullable=False)
    exit_reason: Mapped[str | None] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class TrainingSlot(Base):
    __tablename__ = "training_slots"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    training_id: Mapped[str | None] = mapped_column(ForeignKey("trainings.id"))


class TrainingQuestion(Base):
    __tablename__ = "training_questions"
    __table_args__ = (UniqueConstraint("training_id", "main", "follow", name="uq_training_question"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    training_id: Mapped[str] = mapped_column(ForeignKey("trainings.id"), index=True, nullable=False)
    main: Mapped[int] = mapped_column(Integer, nullable=False)
    follow: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    basis: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    dimension_ids: Mapped[list | None] = mapped_column(JSON)
    reference_points: Mapped[list | None] = mapped_column(JSON)
    draft: Mapped[str] = mapped_column(Text, default="", nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    transcript_id: Mapped[str | None] = mapped_column(String(36))
    keyboard_reason: Mapped[str | None] = mapped_column(String(40))
    fault_id: Mapped[str | None] = mapped_column(String(36))
    asked_at: Mapped[datetime | None] = mapped_column(DateTime)


class SpeechTranscript(Base):
    __tablename__ = "speech_transcripts"
    __table_args__ = (UniqueConstraint("owner_id", "request_key", name="uq_speech_request"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    question_id: Mapped[str] = mapped_column(ForeignKey("training_questions.id"), index=True, nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    audio_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class TrainingAnswer(Base):
    __tablename__ = "training_answers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question_id: Mapped[str] = mapped_column(ForeignKey("training_questions.id"), unique=True, nullable=False)
    training_id: Mapped[str] = mapped_column(ForeignKey("trainings.id"), index=True, nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    transcript_id: Mapped[str | None] = mapped_column(ForeignKey("speech_transcripts.id"))
    fault_reason: Mapped[str | None] = mapped_column(String(40))
    raw_transcript: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (UniqueConstraint("owner_id", "step_key", name="uq_generation_step"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    training_id: Mapped[str | None] = mapped_column(ForeignKey("trainings.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    auth_session_id: Mapped[str | None] = mapped_column(String(36))
    output: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(48))
    error_message: Mapped[str | None] = mapped_column(String(200))
    diagnostic: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class PracticeTask(Base):
    __tablename__ = "practice_tasks"
    __table_args__ = (UniqueConstraint("source_id", "question_id", name="uq_practice_source_question"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("trainings.id"), nullable=False)
    question_id: Mapped[str] = mapped_column(ForeignKey("training_questions.id"), nullable=False)
    answer_id: Mapped[str] = mapped_column(ForeignKey("training_answers.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    focus: Mapped[str] = mapped_column(String(80), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str] = mapped_column(Text, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

