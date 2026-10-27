import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.auth import Config, Current, Db, Protected
from app.config import BACKEND_DIR, Settings
from app.errors import ApiError
from app.material_extract import (
    RULES_VERSION,
    extract_job,
    extract_resume,
    extraction_evidence,
    job_title,
)
from app.material_schemas import JobParse, JobSave, Rename, ResumeSave, Revision
from app.models import Material, MaterialFile, MaterialVersion, new_id, now_utc

router = APIRouter(prefix="/api/v1/materials", tags=["materials"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=64)]
ERRORS = {
    "NO_TEXT": "文件中没有可提取文字，请重新上传文字版文件；扫描件OCR尚未接入。",
    "FILE_ENCRYPTED": "文件已加密，请解密后重新上传。",
    "FILE_COMPLEX": "文件结构过于复杂，请精简后重新上传。",
    "TEXT_TOO_LONG": "文件文字超过处理上限，请精简后重新上传。",
    "EXTRACT_TIMEOUT": "原文提取超时，请重新上传较小的文字版文件。",
}


def hash_value(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def private_path(settings: Settings, file_id: str) -> Path:
    # Only server-generated UUIDs become storage names; uploaded names never become paths.
    try:
        canonical = str(UUID(file_id))
    except ValueError:
        raise ApiError(404, "FILE_NOT_FOUND", "原文件不存在") from None
    return settings.material_directory.resolve() / canonical


def own(db, owner: str, material_id: str, kind: str, *, lock=False):
    query = select(Material).where(Material.id == material_id, Material.owner_id == owner,
                                   Material.kind == kind, Material.deleted_at.is_(None))
    row = db.scalar(query.with_for_update() if lock else query)
    if not row:
        raise ApiError(404, "MATERIAL_NOT_FOUND", "材料不存在或不可访问")
    return row


def require_revision(row: Material, revision: int | None):
    if revision != row.revision:
        raise ApiError(409, "MATERIAL_CONFLICT", "材料已在其他页面更新，请刷新后重新校对")


def retry_record(db, owner, kind, key, request_hash):
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", key):
        raise ApiError(422, "INVALID_INPUT", "请求编号格式不正确")
    row = db.scalar(select(Material).where(Material.owner_id == owner, Material.kind == kind,
                                           Material.request_key == key))
    if row:
        if row.request_hash != request_hash or row.deleted_at:
            raise ApiError(409, "REQUEST_CONFLICT", "请求编号已使用，请重新发起操作")
        return row
    return None


def payload(db, row: Material):
    stamp = row.updated_at.isoformat(timespec="seconds") + "Z"
    data = {"id": row.id, "title": row.title, "status": row.status, "revision": row.revision,
            "version": row.version, "source": row.source, "updatedAt": stamp,
            "errorCode": row.error_code, "errorMessage": row.error_message,
            "parserVersion": row.parser_version, "extractedFields": row.extracted_fields.get("fields", {}),
            "sourceEvidence": row.extracted_fields.get("evidence", {})}
    from app.models import GenerationJob
    from app.training_service import public_job
    parsing = db.scalar(select(GenerationJob).where(GenerationJob.owner_id == row.owner_id,
                         GenerationJob.step_key.like(f"material:{row.id}:revision:%"))
                         .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc()))
    data["parsingJob"] = public_job(parsing) if parsing else None
    data["userEditedFields"] = [key for key, value in row.fields.items()
                               if value != data["extractedFields"].get(key)]
    if row.kind == "resume":
        file = db.get(MaterialFile, row.file_id)
        fields = row.fields
        skills = list(dict.fromkeys(s.strip() for s in re.split(r"[、,，;；\n]+", fields.get("skills", "")) if s.strip()))[:6]
        data.update({"fields": fields, "file": file.filename, "type": file.file_type,
                     "size": file.size, "sha256": file.sha256,
                     "projects": sum(bool(p.get("name", "").strip()) for p in fields.get("projects", [])),
                     "skills": skills})
    else:
        data.update(row.fields)
        data.update({"parsed": row.status != "failed", "analyzedSource": row.source})
    return data


@router.post("/{kind}/{material_id}/model-parse", status_code=202)
def model_parse(kind: str, material_id: str, body: Revision, request: Request, db: Db, context: Protected):
    from app.material_ai import queue
    if kind not in {"resumes", "jobs"}:
        raise ApiError(404, "MATERIAL_NOT_FOUND", "材料不存在")
    row = own(db, context.user.id, material_id, "resume" if kind == "resumes" else "job", lock=True)
    require_revision(row, body.revision)
    if row.status == "confirmed":
        raise ApiError(409, "MATERIAL_ALREADY_CONFIRMED", "已确认材料请通过校对编辑，模型不能覆盖")
    job = queue(db, row)
    db.commit()
    request.app.state.generation.ensure(job.id)
    from app.training_service import public_job
    return {"job": public_job(job), "material": payload(db, row)}


@router.get("/{kind}/{material_id}")
def read_material(kind: str, material_id: str, db: Db, context: Current):
    if kind not in {"resumes", "jobs"}:
        raise ApiError(404, "MATERIAL_NOT_FOUND", "材料不存在")
    return {"material": payload(db, own(db, context.user.id, material_id, "resume" if kind == "resumes" else "job"))}


def list_rows(db, owner, kind, offset, limit):
    filters = (Material.owner_id == owner, Material.kind == kind, Material.deleted_at.is_(None))
    total = db.scalar(select(func.count()).select_from(Material).where(*filters))
    rows = db.scalars(select(Material).where(*filters).order_by(Material.updated_at.desc(), Material.id)
                      .offset(offset).limit(limit))
    return {"items": [payload(db, row) for row in rows], "total": total}


@router.get("/resumes")
def resumes(db: Db, context: Current, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    return list_rows(db, context.user.id, "resume", offset, limit)


@router.get("/jobs")
def jobs(db: Db, context: Current, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    return list_rows(db, context.user.id, "job", offset, limit)


def extract_document(path, kind, settings):
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(BACKEND_DIR / "app" / "material_worker.py"),
             str(path), kind, str(settings.material_text_limit)],
            capture_output=True, timeout=settings.material_extract_timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
        if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
            return {"error": "EXTRACT_TIMEOUT"}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "EXTRACT_TIMEOUT"}
    except (ValueError, OSError):
        raise ApiError(503, "EXTRACT_UNAVAILABLE", "原文提取暂不可用，请稍后重试", retryable=True) from None


@router.post("/resumes", status_code=201)
async def upload_resume(
    request: Request, db: Db, settings: Config, context: Protected, idempotency_key: Key,
    filename: str = Query(min_length=1, max_length=180),
    replace_id: str | None = None, revision: int | None = Query(None, ge=1),
):
    if any(c in filename for c in '/\\:\r\n\x00'):
        raise ApiError(422, "INVALID_FILENAME", "文件名称不合法")
    kind = filename.rsplit(".", 1)[-1].upper()
    if kind not in {"PDF", "DOCX", "TXT"}:
        raise ApiError(415, "UNSUPPORTED_FILE", "仅支持PDF、DOCX、TXT文件")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/octet-stream":
        raise ApiError(415, "UNSUPPORTED_UPLOAD", "请以原文件上传")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > settings.material_max_bytes:
            raise ApiError(413, "FILE_TOO_LARGE", "文件不能超过10MB")
        content.extend(chunk)
    if not content:
        raise ApiError(422, "EMPTY_FILE", "文件为空，请重新选择")
    sha = hashlib.sha256(content).hexdigest()
    request_hash = hash_value([filename, sha])
    if not replace_id:
        existing = retry_record(db, context.user.id, "resume", idempotency_key, request_hash)
        if existing:
            return {"material": payload(db, existing)}
    else:
        row = own(db, context.user.id, replace_id, "resume")
        require_revision(row, revision)
    file_id = new_id()
    path = private_path(settings, file_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    committed = False
    try:
        with path.open("xb") as handle:
            handle.write(content)
        extraction = await run_in_threadpool(extract_document, path, kind, settings)
        code = extraction.get("error")
        if code == "INVALID_FILE":
            raise ApiError(415, "INVALID_FILE", "文件内容与格式不符或已损坏，请重新上传")
        source = extraction.get("text", "")
        fields = extract_resume(source)
        if replace_id:
            # Extraction ran outside the DB lock; refresh before applying its result.
            db.expire_all()
            row = own(db, context.user.id, replace_id, "resume", lock=True)
            require_revision(row, revision)
            row.revision += 1
        else:
            row = Material(owner_id=context.user.id, kind="resume", title=filename.rsplit(".", 1)[0],
                           request_key=idempotency_key, request_hash=request_hash)
            db.add(row)
        db.add(MaterialFile(id=file_id, owner_id=context.user.id, filename=filename,
                            file_type=kind, size=len(content), sha256=sha))
        db.flush()
        row.file_id, row.source, row.fields = file_id, source, fields
        row.parser_version = RULES_VERSION
        row.extracted_fields = {"fields": fields, "evidence": extraction_evidence(source, fields)}
        row.status = "failed" if code else "pending"
        row.error_code, row.error_message = code, ERRORS.get(code)
        row.updated_at = now_utc()
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if not replace_id:
                existing = retry_record(db, context.user.id, "resume", idempotency_key, request_hash)
                if existing:
                    return {"material": payload(db, existing)}
            raise ApiError(409, "MATERIAL_CONFLICT", "材料状态已改变，请刷新后重试") from None
        committed = True
        return {"material": payload(db, row)}
    finally:
        if not committed:
            path.unlink(missing_ok=True)


def confirm(db, row, fields):
    if row.status == "failed":
        raise ApiError(409, "MATERIAL_NOT_READY", "材料提取失败，请重新上传或解析")
    snapshot = {"kind": row.kind, "source": row.source, "fileId": row.file_id,
                "fields": fields, "parserVersion": row.parser_version,
                "extractedFields": row.extracted_fields}
    if len(json.dumps(snapshot, ensure_ascii=False)) > 750_000:
        raise ApiError(422, "FIELDS_TOO_LONG", "校对内容超过处理上限，请精简后保存")
    content = {key: snapshot[key] for key in ("kind", "source", "fields")}
    content_hash = hash_value(content)
    latest = db.scalar(select(MaterialVersion).where(MaterialVersion.material_id == row.id,
                                                     MaterialVersion.number == row.version))
    same = latest is not None and {key: latest.snapshot.get(key) for key in content} == content
    if latest is None or not same:
        row.version += 1
        db.add(MaterialVersion(material_id=row.id, number=row.version, snapshot=snapshot,
                               content_hash=content_hash))
    if row.kind == "job":
        row.title = job_title(row.title, row.fields, fields)
    row.fields, row.status = fields, "confirmed"
    row.revision += 1
    row.updated_at = now_utc()
    db.commit()
    return {"material": payload(db, row)}


@router.put("/resumes/{material_id}")
def save_resume(material_id: str, body: ResumeSave, db: Db, context: Protected):
    row = own(db, context.user.id, material_id, "resume", lock=True)
    require_revision(row, body.revision)
    return confirm(db, row, body.fields.model_dump())


@router.patch("/resumes/{material_id}")
def rename_resume(material_id: str, body: Rename, db: Db, context: Protected):
    row = own(db, context.user.id, material_id, "resume", lock=True)
    require_revision(row, body.revision)
    row.title, row.updated_at = body.title, now_utc()
    row.revision += 1
    db.commit()
    return {"material": payload(db, row)}


@router.delete("/resumes/{material_id}")
def delete_resume(material_id: str, body: Revision, db: Db, context: Protected):
    row = own(db, context.user.id, material_id, "resume", lock=True)
    require_revision(row, body.revision)
    from app.control_journal import record
    record(db.info["settings"], "material_deleted", row.id)
    row.deleted_at, row.updated_at = now_utc(), now_utc()
    row.revision += 1
    db.commit()
    return {"message": "简历已移除，源材料24小时内清理；已有训练保留必要快照。"}


@router.get("/resumes/{material_id}/file")
def download_resume(material_id: str, db: Db, settings: Config, context: Current):
    row = own(db, context.user.id, material_id, "resume")
    file = db.get(MaterialFile, row.file_id)
    path = private_path(settings, file.id)
    if not path.is_file():
        raise ApiError(404, "FILE_NOT_FOUND", "原文件暂不可用，请重新上传")
    return FileResponse(path, filename=file.filename, media_type="application/octet-stream",
                        headers={"Content-Security-Policy": "default-src 'none'; sandbox"})


@router.post("/jobs", status_code=201)
def parse_new_job(body: JobParse, db: Db, settings: Config, context: Protected, idempotency_key: Key):
    validate_source(body.source, settings)
    request_hash = hash_value(body.source)
    existing = retry_record(db, context.user.id, "job", idempotency_key, request_hash)
    if existing:
        return {"material": payload(db, existing)}
    row = Material(owner_id=context.user.id, kind="job", title="新增岗位 JD",
                   request_key=idempotency_key, request_hash=request_hash, revision=1, version=0)
    parse_job(row, body.source)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = retry_record(db, context.user.id, "job", idempotency_key, request_hash)
        if existing:
            return {"material": payload(db, existing)}
        raise ApiError(409, "MATERIAL_CONFLICT", "材料状态已改变，请刷新后重试") from None
    return {"material": payload(db, row)}


def validate_source(source, settings):
    if not source.strip() or len(source) > settings.jd_text_limit or "\x00" in source:
        raise ApiError(422, "INVALID_JD", f"请填写有效岗位描述，原文最多{settings.jd_text_limit}个字符（含空格和换行）")


def parse_job(row, source):
    fields = extract_job(source)
    row.title = job_title(row.title, row.fields, fields)
    row.source, row.fields, row.status = source, fields, "pending"
    row.extracted_fields = {"fields": fields, "evidence": extraction_evidence(source, fields)}
    row.error_code = row.error_message = None
    row.parser_version, row.updated_at = RULES_VERSION, now_utc()


@router.post("/jobs/{material_id}/parse")
def reparse_job(material_id: str, body: JobParse, db: Db, settings: Config, context: Protected):
    validate_source(body.source, settings)
    row = own(db, context.user.id, material_id, "job", lock=True)
    require_revision(row, body.revision)
    parse_job(row, body.source)
    row.revision += 1
    db.commit()
    return {"material": payload(db, row)}


@router.put("/jobs/{material_id}")
def save_job(material_id: str, body: JobSave, db: Db, context: Protected):
    row = own(db, context.user.id, material_id, "job", lock=True)
    require_revision(row, body.revision)
    if body.source != row.source:
        raise ApiError(409, "ANALYSIS_STALE", "原文已修改，请重新解析后再保存")
    return confirm(db, row, body.fields.model_dump())


@router.patch("/jobs/{material_id}")
def rename_job(material_id: str, body: Rename, db: Db, context: Protected):
    row = own(db, context.user.id, material_id, "job", lock=True)
    require_revision(row, body.revision)
    row.title, row.updated_at = body.title, now_utc()
    row.revision += 1
    db.commit()
    return {"material": payload(db, row)}


@router.get("/{kind}/{material_id}/versions")
def versions(kind: str, material_id: str, db: Db, context: Current):
    if kind not in {"resumes", "jobs"}:
        raise ApiError(404, "MATERIAL_NOT_FOUND", "材料不存在")
    row = own(db, context.user.id, material_id, "resume" if kind == "resumes" else "job")
    items = db.scalars(select(MaterialVersion).where(MaterialVersion.material_id == row.id)
                       .order_by(MaterialVersion.number))
    return {"items": [{"version": v.number, "snapshot": v.snapshot} for v in items]}
