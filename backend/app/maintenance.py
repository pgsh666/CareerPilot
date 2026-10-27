"""Local retention, private daily backups and guarded restores. Never includes .env/audio."""
import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import MetaData, delete, select, update

from app import control_journal as controls
from app.db import session_factory
from app.errors import ApiError
from app.maintenance_storage import (
    FINANCE_TABLES,
    atomic_json,
    checkpoint_billing,
    load_billing,
    read_tables,
    restore_values,
)
from app.models import (
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

log = logging.getLogger("careerpilot")
BACKUP_NAME = re.compile(r"careerpilot-\d{8}T\d{12}-[a-f0-9]{8}\.zip")


def private_directory(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    marker = path / ".careerpilot-private"
    if not marker.exists():
        if os.name == "nt":
            # Restrict just this project directory, never the parent drive/user folder.
            identity = subprocess.check_output(["whoami"], text=True).strip()
            result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                                     identity + ":(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                                    capture_output=True, creationflags=0x08000000)
            if result.returncode:
                raise ApiError(503, "BACKUP_PERMISSIONS_FAILED", "无法限制备份目录权限，未写入个人数据")
        else:
            path.chmod(0o700)
        marker.touch()
    return path


def material_path(settings, file_id):
    canonical = str(UUID(file_id))
    root = settings.material_directory.resolve()
    path = (root / canonical).resolve()
    if path.parent != root or path.is_symlink():
        raise ApiError(503, "MATERIAL_PATH_INVALID", "材料路径校验失败")
    return path


def sync_controls(db, settings):
    controls.initialize(settings)
    for user in db.scalars(select(User)):
        if user.closed_at:
            controls.record(settings, "account_closed", user.id, at=user.closed_at)
            if not user.email.endswith("@closed.invalid"):
                user.former_email, user.email = user.email, f"closed-{user.id}@closed.invalid"
            user.enabled = False
        elif not user.enabled:
            controls.record(settings, "account_status", user.id, at=user.updated_at, enabled=False)
    for material in db.scalars(select(Material).where(Material.deleted_at.is_not(None))):
        controls.record(settings, "material_deleted", material.id, at=material.deleted_at)


def apply_controls(db, rows):
    for marker in rows:
        stamp = datetime.fromisoformat(marker["at"])
        if marker["kind"] == "material_deleted":
            material = db.get(Material, marker["target"])
            if material:
                material.deleted_at = min(material.deleted_at, stamp) if material.deleted_at else stamp
        else:
            user = db.get(User, marker["target"])
            if not user:
                continue
            if marker["kind"] == "account_closed":
                user.closed_at = min(user.closed_at, stamp) if user.closed_at else stamp
                user.enabled = False
                if not user.email.endswith("@closed.invalid"):
                    user.former_email = user.email
                user.email = f"closed-{user.id}@closed.invalid"
            elif not user.closed_at:
                user.enabled = marker["enabled"]


def cleanup(engine, settings, *, at=None):
    """Runs at startup and every minute; deletion can be earlier than the 24h deadline."""
    at = at or now_utc()
    counts = {"materials": 0, "accounts": 0, "temporaryAudio": 0}
    with controls.journal_lock(settings, "maintenance"):
        with session_factory(engine).begin() as db:
            db.execute(delete(VerificationCode).where(VerificationCode.expires_at <= at))
            db.execute(delete(RateBucket).where(RateBucket.expires_at <= at))
            # A process crash cannot leave a dispatched attempt "running" forever.
            # created_at is set again at dispatch, so time spent in the queue is excluded.
            orphaned = list(db.scalars(select(ModelSpend).where(ModelSpend.state == "running",
                              ModelSpend.created_at < at - timedelta(seconds=settings.model_timeout_seconds + 45))))
            for spend in orphaned:
                spend.state, spend.error_code, spend.finished_at = "unknown", "MODEL_COST_UNCERTAIN", at
                if "-attempt-" in spend.request_key:
                    job = db.get(GenerationJob, spend.request_key.rsplit("-attempt-", 1)[0])
                    if job and job.state == "running":
                        job.state, job.error_code = "failed", "MODEL_COST_UNCERTAIN"
                        job.error_message = "上次进程未取得完整结果，费用保留预留待核实，未自动重试。"
                        job.finished_at = at
                        if job.kind == "report" and job.training_id:
                            db.get(Training, job.training_id).report_state = "failed"
            sync_controls(db, settings)
            apply_controls(db, controls.load(settings, required=True))
            db.flush()
            expired = list(db.scalars(select(User).where(User.closed_at <= at - timedelta(days=30), User.purged_at.is_(None))))
            owners = [u.id for u in expired]
            mats = list(db.scalars(select(Material).where(Material.deleted_at.is_not(None))))
            if owners:
                mats += list(db.scalars(select(Material).where(Material.owner_id.in_(owners), Material.deleted_at.is_(None))))
            for material in mats:
                if not material.source and not material.file_id and not material.fields and material.status == "purged":
                    continue
                # Parse caches also contain personal material text, not just the material row.
                jobs = list(db.scalars(select(GenerationJob).where(GenerationJob.kind == "material_parse", GenerationJob.owner_id == material.owner_id)))
                for job in jobs:
                    if job.input_snapshot.get("material_id") == material.id:
                        for spend in db.scalars(select(ModelSpend).where(ModelSpend.request_key.like(job.id + "-attempt-%"))):
                            spend.result, spend.pricing = None, {**spend.pricing, "personalDataPurged": True}
                        job.input_snapshot, job.output, job.state = {}, None, "stale"
                db.execute(delete(MaterialVersion).where(MaterialVersion.material_id == material.id))
                file_id = material.file_id
                material.file_id = None
                material.source, material.fields, material.extracted_fields = "", {}, {}
                material.title, material.status = "已删除材料", "purged"
                material.error_code = material.error_message = None
                material.deleted_at = material.deleted_at or at
                db.flush()
                if file_id:
                    # MaterialFile is immutable and not shared between independent uploads.
                    if not db.scalar(select(Material.id).where(Material.file_id == file_id)):
                        material_path(settings, file_id).unlink(missing_ok=True)
                        db.execute(delete(MaterialFile).where(MaterialFile.id == file_id))
                counts["materials"] += 1
            for user in expired:
                db.execute(delete(AvatarImage).where(AvatarImage.owner_id == user.id))
                training_ids = select(Training.id).where(Training.owner_id == user.id)
                db.execute(delete(PracticeTask).where(PracticeTask.owner_id == user.id))
                db.execute(delete(GenerationJob).where(GenerationJob.owner_id == user.id))
                db.execute(delete(TrainingAnswer).where(TrainingAnswer.training_id.in_(training_ids)))
                db.execute(delete(SpeechTranscript).where(SpeechTranscript.owner_id == user.id))
                db.execute(delete(TrainingQuestion).where(TrainingQuestion.training_id.in_(training_ids)))
                db.execute(delete(TrainingSlot).where(TrainingSlot.owner_id == user.id))
                db.execute(delete(Training).where(Training.owner_id == user.id))
                db.execute(delete(Material).where(Material.owner_id == user.id))
                for file in db.scalars(select(MaterialFile).where(MaterialFile.owner_id == user.id)):
                    material_path(settings, file.id).unlink(missing_ok=True)
                    db.delete(file)
                db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
                db.execute(delete(VerificationCode).where(VerificationCode.owner_id == user.id))
                # Anonymous accounting remains independent of user lifecycle and re-registration.
                for spend in db.scalars(select(ModelSpend).where(ModelSpend.owner_id == user.id)):
                    spend.owner_id, spend.result = None, None
                    spend.pricing = {**spend.pricing, "personalDataPurged": True}
                user.name, user.avatar, user.password_hash, user.former_email = "已注销", "default", "!closed", None
                user.role, user.enabled, user.email_verified, user.purged_at = "user", False, False, at
                counts["accounts"] += 1
        root = settings.speech_temporary_directory.resolve()
        if root.exists():
            for path in root.iterdir():
                if path.is_file() and not path.is_symlink() and re.fullmatch(r"(?:asr-[a-f0-9-]{36}\.audio|(?:tts-)?[a-f0-9-]{36}\.wav)", path.name):
                    if at.timestamp() - path.stat().st_mtime > 600:
                        path.unlink(missing_ok=True)
                        counts["temporaryAudio"] += 1
        checkpoint_billing(engine, settings)
    return counts


def backup(engine, settings):
    """Reflection permits backing up the old schema BEFORE migrations are applied."""
    root = private_directory(settings.backup_directory)
    with controls.journal_lock(settings, "maintenance"):
        controls.initialize(settings)
        checkpoint_billing(engine, settings)
        tables = read_tables(engine)
        from app.models import new_id
        name = "careerpilot-" + now_utc().strftime("%Y%m%dT%H%M%S%f") + "-" + new_id().replace("-", "")[:8] + ".zip"
        destination = root / name
        temporary = root / (name + ".tmp")
        content = {"database.json": controls.encoded(tables)}
        for row in tables.get("material_files", []):
            path = material_path(settings, row["id"])
            if not path.is_file():
                raise ApiError(503, "BACKUP_MATERIAL_MISSING", "材料原文件缺失，备份未标记为成功")
            content["materials/" + row["id"]] = path.read_bytes()
        manifest = {"format": "careerpilot-backup-v1", "createdAt": now_utc().isoformat(),
                    "database": engine.url.database, "tables": {k: len(v) for k, v in tables.items()},
                    "sha256": {k: hashlib.sha256(v).hexdigest() for k, v in content.items()}}
        try:
            with zipfile.ZipFile(temporary, "x", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", controls.encoded(manifest))
                for path, value in content.items():
                    archive.writestr(path, value)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        verify_backup(destination)
        atomic_json(controls.root_for(settings) / "last-backup.json", {"createdAt": manifest["createdAt"], "file": name})
        for path in root.iterdir():
            if BACKUP_NAME.fullmatch(path.name) and path.is_file() and not path.is_symlink():
                try:
                    created = datetime.fromisoformat(verify_backup(path)[0]["createdAt"])
                    if created < now_utc() - timedelta(days=7):
                        path.unlink()
                except ApiError:
                    log.error("backup_retention_unverified_file")
        return {"path": str(destination), "createdAt": manifest["createdAt"], "tables": manifest["tables"]}


def verify_backup(path):
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            if manifest["format"] != "careerpilot-backup-v1":
                raise ValueError("format")
            expected = manifest["sha256"]
            if set(archive.namelist()) != {"manifest.json", *expected} or "database.json" not in expected:
                raise ValueError("entries")
            content = {}
            for name, digest in expected.items():
                if name != "database.json" and not re.fullmatch(r"materials/[a-f0-9-]{36}", name):
                    raise ValueError("entry")
                data = archive.read(name)
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("hash")
                content[name] = data
            return manifest, content
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        raise ApiError(422, "BACKUP_INVALID", "备份格式或校验和错误，未恢复数据") from None


def restore(engine, settings, path, *, confirmed_database):
    if confirmed_database != str(engine.url.database):
        raise ApiError(409, "RESTORE_TARGET_CONFIRMATION", "目标库名确认不一致，未恢复数据")
    manifest, content = verify_backup(Path(path).resolve())
    markers = controls.load(settings, required=True)
    billing = load_billing(settings, required=True)
    # Back up the currently selected target before any overwrite; never touch old careerpilot.
    before = backup(engine, settings)
    billing = load_billing(settings, required=True)
    tables = json.loads(content["database.json"])
    metadata = MetaData()
    metadata.reflect(engine)
    allowed = set(metadata.tables) - {"alembic_version"}
    if not set(tables) - {"alembic_version"} <= allowed:
        raise ApiError(422, "BACKUP_SCHEMA_INVALID", "备份包含当前数据库不支持的表")
    for name in FINANCE_TABLES:
        tables[name] = billing["tables"].get(name, [])
    # A restored financial cache is metadata only: do not resurrect personal model outputs.
    for spend in tables.get("model_spends", []):
        spend["owner_id"], spend["result"] = None, None
        if spend["state"] == "running":
            spend["state"], spend["error_code"] = "unknown", "RESTORE_FEE_UNCERTAIN"
        elif spend["state"] == "reserved":
            spend["state"], spend["error_code"], spend["charged_micro"] = "cancelled", "RESTORE_NOT_SENT", 0
    # Derive counters from the preserved ledger; lifetime test costs never roll back.
    for bucket in tables.get("model_budgets", []):
        rows = [s for s in tables.get("model_spends", []) if s["month_key"] == bucket["key"] or
                (bucket["key"] == "tests:careerpilot" and s["test_mode"]) or
                (bucket["key"] == "smoke:careerpilot" and s["purpose"] == "integration_smoke")]
        bucket["charged_micro"] = sum(s.get("charged_micro") or 0 for s in rows)
        bucket["held_micro"] = sum(s["reserved_micro"] for s in rows if s["state"] in {"running", "unknown", "reserved"})
        bucket["sent_calls"] = sum(s["state"] not in {"cancelled", "reserved"} for s in rows)
        bucket["pending_calls"] = sum(s["state"] == "reserved" for s in rows)
    # Validate every column/type and every file before starting the transaction.
    converted = {name: restore_values(metadata.tables[name], tables.get(name, [])) for name in allowed}
    for row in tables.get("material_files", []):
        data = content.get("materials/" + row["id"])
        if data is None or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ApiError(422, "BACKUP_MATERIAL_INVALID", "备份材料与数据库记录不一致")
        target = material_path(settings, row["id"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    with engine.begin() as connection:
        for table in reversed(metadata.sorted_tables):
            if table.name in allowed:
                connection.execute(delete(table))
        for table in metadata.sorted_tables:
            if table.name in allowed and converted[table.name]:
                connection.execute(table.insert(), converted[table.name])
    with session_factory(engine).begin() as db:
        apply_controls(db, markers)
        db.execute(update(AuthSession).values(revoked_at=now_utc()))
        db.execute(update(Training).where(Training.status == "active").values(status="interrupted", exit_reason="restore",
                   writer_lease=None, writer_session_id=None, writer_seen_at=None, activity_running=False, activity_at=None))
        db.execute(update(GenerationJob).where(GenerationJob.state.in_(["queued", "running", "ready"])).values(state="paused", auth_session_id=None))
    cleanup(engine, settings)
    checkpoint_billing(engine, settings)
    return {"restoredFrom": str(path), "beforeRestore": before["path"], "createdAt": manifest["createdAt"], "sessionsRevoked": True}


class MaintenanceRunner:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self.stop = threading.Event()
        self.thread = None
        self.last_error = None

    def tick(self):
        cleanup(self.engine, self.settings)
        status = controls.root_for(self.settings) / "last-backup.json"
        last = json.loads(status.read_text(encoding="utf-8")) if status.exists() else None
        if not last or (datetime.fromisoformat(last["createdAt"]) + timedelta(hours=8)).date() != (now_utc() + timedelta(hours=8)).date():
            backup(self.engine, self.settings)

    def start(self):
        if self.engine is None or self.settings.environment == "test":
            return
        # Startup is synchronous: no requests accepted before overdue controls/cleanup.
        self.tick()
        def run():
            while not self.stop.wait(60):
                try:
                    self.tick()
                    self.last_error = None
                except Exception:
                    self.last_error = "MAINTENANCE_FAILED"
                    log.exception("maintenance_failed")
        self.thread = threading.Thread(target=run, name="careerpilot-maintenance", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
