import hashlib
import re
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.auth import Current, Db, Protected, hit_limit
from app.db import fresh_authorization
from app.errors import ApiError
from app.models import (
    GenerationJob,
    PracticeTask,
    SpeechTranscript,
    Training,
    TrainingQuestion,
    TrainingSlot,
    new_id,
    now_utc,
)
from app.training_schemas import (
    ActivityInput,
    AnswerInput,
    Confirm,
    DraftInput,
    FaultInput,
    LeaseInput,
    ResumeTraining,
    StartInterview,
    StartPractice,
)
from app.training_service import (
    current_question,
    finish_training,
    next_practice_stage,
    own_training,
    payload,
    public_job,
    resume_training,
    start_interview,
    start_practice,
    submit_answer,
)

router = APIRouter(prefix="/api/v1/training", tags=["training"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=64)]


def valid_key(key):
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", key):
        raise ApiError(422, "INVALID_REQUEST_KEY", "请求编号格式不正确")


def schedule(request, training_id):
    request.app.state.generation.schedule_training(training_id, getattr(request.state, "auth_session_id", None))


@router.post("/interviews", status_code=201)
def create_interview(body: StartInterview, request: Request, db: Db, context: Protected, idempotency_key: Key):
    valid_key(idempotency_key)
    row = start_interview(db, context.user.id, body, idempotency_key)
    result = payload(db, row)
    schedule(request, row.id)
    return {"training": result}


@router.post("/practices", status_code=201)
def create_practice(body: StartPractice, request: Request, db: Db, context: Protected, idempotency_key: Key):
    valid_key(idempotency_key)
    row = start_practice(db, context.user.id, body, idempotency_key)
    schedule(request, row.id)
    return {"training": payload(db, row)}


@router.get("/summary")
def summary(db: Db, context: Current):
    slot = db.get(TrainingSlot, context.user.id)
    row = own_training(db, context.user.id, slot.training_id) if slot and slot.training_id else None
    count = db.scalar(select(func.count()).select_from(Training).where(Training.owner_id == context.user.id,
                          Training.mode == "interview", Training.status == "completed"))
    duration = db.scalar(select(func.coalesce(func.sum(Training.active_ms), 0)).where(Training.owner_id == context.user.id))
    tasks = list(db.scalars(select(PracticeTask).where(PracticeTask.owner_id == context.user.id)
                            .order_by(PracticeTask.created_at.desc(), PracticeTask.id)))
    return {"active": payload(db, row) if row and row.status not in {"completed", "early_ended"} else None,
            "completedInterviews": count, "practiceMinutes": int(duration) // 60_000,
            "minutesState": "visible_answering",
            "tasks": [{"id": t.id, "title": t.title, "focus": t.focus, "quote": t.quote,
                       "suggestion": t.suggestion, "sourceId": t.source_id, "questionId": t.question_id,
                       "done": t.done} for t in tasks]}


@router.get("/history")
def history(db: Db, context: Current, mode: Literal["all", "interview", "practice"] = "all",
            status: str = Query("all", max_length=24), role: str = Query("all", max_length=80),
            target: str = Query("all", max_length=100), days: int = Query(0, ge=0, le=3660),
            offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    rows = list(db.scalars(select(Training).where(Training.owner_id == context.user.id)
                           .order_by(Training.started_at.desc(), Training.id)))
    def match(row):
        j = row.job_snapshot
        target_id = str(j.get("id", "")) + "-v" + str(j.get("version", 0))
        return ((mode == "all" or row.mode == mode) and (status == "all" or row.status == status)
                and (role == "all" or j["fields"]["role"] == role)
                and (target == "all" or target_id == target)
                and (not days or row.started_at >= now_utc() - timedelta(days=days)))
    filtered = [r for r in rows if match(r)]
    return {"items": [payload(db, row) for row in filtered[offset:offset + limit]], "total": len(filtered)}


@router.get("/filters")
def filters(db: Db, context: Current):
    rows = db.execute(select(Training.job_snapshot).where(Training.owner_id == context.user.id)).all()
    targets = {}
    for (snapshot,) in rows:
        key = str(snapshot["id"]) + "-v" + str(snapshot["version"])
        targets[key] = {"id": key, "name": snapshot["title"], "version": snapshot["version"],
                        "role": snapshot["fields"]["role"], "direction": snapshot["fields"]["direction"]}
    return {"targets": list(targets.values())}


@router.get("/trend")
def trend(db: Db, context: Current, role: str = Query("all", max_length=80),
          target: str = Query("all", max_length=100), days: int = Query(30, ge=0, le=3660),
          scoring_version: str = Query("auto", max_length=40)):
    from app.scoring import VERSION
    rows = list(db.scalars(select(Training).where(Training.owner_id == context.user.id, Training.mode == "interview")
                           .order_by(Training.started_at.desc(), Training.id)))
    rows = [r for r in rows if (role == "all" or r.job_snapshot["fields"]["role"] == role)
            and (target == "all" or f'{r.job_snapshot["id"]}-v{r.job_snapshot["version"]}' == target)
            and (not days or r.started_at >= now_utc() - timedelta(days=days))]
    eligible = [r for r in rows if r.status == "completed" and r.report_state == "ready" and r.scoring_snapshot
                and (r.report or {}).get("scoring", {}).get("state") == "ready"
                and r.report["scoring"].get("score") is not None]
    versions = {VERSION: {"id": VERSION, "approvedOn": "2026-10-26", "samples": 0}}
    for row in rows:
        if row.scoring_snapshot:
            versions.setdefault(row.scoring_version, {"id": row.scoring_version,
                                "approvedOn": row.scoring_snapshot.get("approvedOn", ""), "samples": 0})
    for row in eligible:
        versions[row.scoring_version]["samples"] += 1
    choices = sorted(versions.values(), key=lambda v: (v["approvedOn"], v["id"]), reverse=True)
    selected = scoring_version
    if selected == "auto":
        selected = next((v["id"] for v in choices if v["samples"]), VERSION)
    candidates = [r for r in eligible if r.scoring_version == selected]
    # With "all" filters, choose and label one latest comparable group; never mix JD/directions.
    anchor = next(iter(candidates), None)
    same = [r for r in candidates if r.job_snapshot["id"] == anchor.job_snapshot["id"]
            and r.job_snapshot["version"] == anchor.job_snapshot["version"]
            and r.scoring_snapshot["roleKey"] == anchor.scoring_snapshot["roleKey"]] if anchor else []
    dimensions = ([anchor.scoring_snapshot["dimensions"][3], anchor.scoring_snapshot["dimensions"][1]] if anchor else [])
    points = []
    for row in sorted(same, key=lambda r: (r.finished_at or r.started_at, r.id)):
        scores = {d["id"]: d["score"] for d in row.report["scoring"]["dimensions"]}
        points.append({"id": row.id, "at": (row.finished_at or row.started_at).isoformat() + "Z",
                       "values": [scores[d["id"]] for d in dimensions], "coverage": row.report["scoring"]["evidenceCoverage"]})
    return {"version": selected, "versions": choices, "sampleCount": len(points), "points": points,
            "dimensions": [{"id": d["id"], "name": d["name"]} for d in dimensions],
            "group": {"target": f'{anchor.job_snapshot["id"]}-v{anchor.job_snapshot["version"]}',
                      "title": anchor.job_snapshot["title"], "role": anchor.job_snapshot["fields"]["role"],
                      "direction": anchor.job_snapshot["fields"]["direction"], "jdVersion": anchor.job_snapshot["version"]} if anchor else None}


@router.post("/sessions/{training_id}/activity")
def activity(training_id: str, body: ActivityInput, request: Request, db: Db, context: Protected):
    row = own_training(db, context.user.id, training_id, lock=True)
    from app.training_lease import require_writer
    require_writer(row, request.headers.get("X-Training-Lease"), context.session.id)
    if body.lease != row.writer_lease:
        raise ApiError(409, "TRAINING_READ_ONLY", "计时租约与当前作答端不一致")
    now = now_utc()
    same = row.activity_lease == body.lease
    if not same and row.activity_running and row.activity_at and (now - row.activity_at).total_seconds() < 30:
        return {"accepted": False, "activeSeconds": row.active_ms // 1000}
    if same and body.sequence <= row.activity_sequence:
        return {"accepted": True, "activeSeconds": row.active_ms // 1000}
    receiving = row.status == "active" and row.phase == "answering"
    asr = db.scalar(select(GenerationJob.id).where(GenerationJob.training_id == row.id,
                    GenerationJob.kind == "asr", GenerationJob.state == "running"))
    receiving = receiving and not asr
    if same and row.activity_running and row.activity_at and receiving:
        wall_ms = max(0, int((now - row.activity_at).total_seconds() * 1000))
        if wall_ms <= 30_000:
            row.active_ms += min(body.elapsed_ms, wall_ms, 8000)
    row.activity_lease, row.activity_sequence, row.activity_at = body.lease, body.sequence, now
    row.activity_running = bool(receiving and body.active)
    db.commit()
    return {"accepted": True, "activeSeconds": row.active_ms // 1000}


@router.post("/sessions/{training_id}/lease")
def lease(training_id: str, body: LeaseInput, db: Db, context: Protected):
    from app.training_lease import acquire
    row = own_training(db, context.user.id, training_id, lock=True)
    result = acquire(row, body, context.session.id)
    db.commit()
    return result


@router.get("/sessions/{training_id}")
def read_training(training_id: str, request: Request, db: Db, context: Current):
    row = own_training(db, context.user.id, training_id)
    schedule(request, row.id)
    from app.training_lease import writable
    return {"training": {**payload(db, row), "writeAccess": writable(row, request.headers.get("X-Training-Lease"), context.session.id)}}


@router.post("/sessions/{training_id}/resume")
def resume(training_id: str, body: ResumeTraining, request: Request, db: Db, context: Protected):
    row = resume_training(db, context.user.id, training_id, body.replace_id)
    schedule(request, row.id)
    return {"training": payload(db, row)}


@router.put("/sessions/{training_id}/draft")
def save_draft(training_id: str, body: DraftInput, request: Request, db: Db, context: Protected):
    row = own_training(db, context.user.id, training_id, lock=True)
    from app.training_lease import require_writer
    require_writer(row, request.headers.get("X-Training-Lease"), context.session.id)
    q = current_question(db, row, body.question_id)
    if row.mode == "interview" and (not q.fault_id or q.transcript_id):
        raise ApiError(409, "FORMAL_DRAFT_READONLY", "正式面试仅在语音故障时保存键盘草稿")
    if body.revision != q.draft_revision and body.text != q.draft:
        raise ApiError(409, "DRAFT_CONFLICT", "草稿已在另一页面更新，请先刷新核对")
    if body.text != q.draft:
        q.draft, q.draft_revision = body.text, q.draft_revision + 1
        row.updated_at = now_utc()
    db.commit()
    return {"revision": q.draft_revision, "text": q.draft}


@router.post("/sessions/{training_id}/answers")
def answer(training_id: str, body: AnswerInput, request: Request, db: Db, context: Protected, idempotency_key: Key):
    valid_key(idempotency_key)
    from app.training_lease import require_writer
    require_writer(own_training(db, context.user.id, training_id, lock=True), request.headers.get("X-Training-Lease"), context.session.id)
    row = submit_answer(db, context.user.id, training_id, body, idempotency_key)
    result = payload(db, row)
    schedule(request, row.id)
    return {"training": result}


@router.post("/sessions/{training_id}/end")
def end(training_id: str, body: Confirm, request: Request, db: Db, context: Protected):
    row = own_training(db, context.user.id, training_id, lock=True)
    if row.status not in {"completed", "early_ended"}:
        from app.training_lease import require_writer
        require_writer(row, request.headers.get("X-Training-Lease"), context.session.id)
        finish_training(db, row, early=True)
        db.commit()
    schedule(request, row.id)
    return {"training": payload(db, row)}


@router.post("/sessions/{training_id}/next-stage")
def next_stage(training_id: str, body: Confirm, request: Request, db: Db, context: Protected):
    from app.training_lease import require_writer
    require_writer(own_training(db, context.user.id, training_id, lock=True), request.headers.get("X-Training-Lease"), context.session.id)
    row = next_practice_stage(db, context.user.id, training_id)
    schedule(request, row.id)
    return {"training": payload(db, row)}


@router.get("/jobs/{job_id}")
def read_job(job_id: str, request: Request, db: Db, context: Current):
    job = db.get(GenerationJob, job_id)
    if not job or job.owner_id != context.user.id:
        raise ApiError(404, "JOB_NOT_FOUND", "任务不存在或不可访问")
    request.app.state.generation.ensure(job.id, context.session.id)
    db.refresh(job)
    return {"job": public_job(job)}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, body: Confirm, request: Request, db: Db, context: Protected):
    original = db.get(GenerationJob, job_id)
    if original and original.owner_id == context.user.id and original.training_id:
        row = own_training(db, context.user.id, original.training_id, lock=True)
        if row.status == "active":
            from app.training_lease import require_writer
            require_writer(row, request.headers.get("X-Training-Lease"), context.session.id)
    job = request.app.state.generation.retry(db, context.user.id, job_id)
    return {"job": public_job(job)}


@router.post("/sessions/{training_id}/speech-fault")
def speech_fault(training_id: str, body: FaultInput, request: Request, db: Db, context: Protected):
    row = own_training(db, context.user.id, training_id, lock=True)
    from app.training_lease import require_writer
    require_writer(row, request.headers.get("X-Training-Lease"), context.session.id)
    q = current_question(db, row, body.question_id)
    if row.mode == "interview" and q.transcript_id:
        raise ApiError(409, "TRANSCRIPT_FINAL", "已有成功转写，不能改为键盘作答")
    q.keyboard_reason, q.fault_id = body.reason, q.fault_id or new_id()
    db.commit()
    return {"faultId": q.fault_id, "reason": q.keyboard_reason}


@router.post("/sessions/{training_id}/transcripts", status_code=201)
async def transcribe(training_id: str, request: Request, db: Db, context: Protected, idempotency_key: Key,
                     question_id: str = Query(max_length=64), replace_confirmed: bool = False):
    valid_key(idempotency_key)
    row = own_training(db, context.user.id, training_id)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > request.app.state.settings.speech_max_bytes:
            raise ApiError(413, "AUDIO_TOO_LARGE", "录音文件超过处理上限")
        data.extend(chunk)
    if not data:
        raise ApiError(422, "EMPTY_AUDIO", "录音为空，请重试")
    audio_hash = hashlib.sha256(data).hexdigest()
    old = db.scalar(select(SpeechTranscript).where(SpeechTranscript.owner_id == context.user.id,
                                                   SpeechTranscript.request_key == idempotency_key))
    if old:
        original_q = db.get(TrainingQuestion, old.question_id)
        if old.audio_hash != audio_hash or old.question_id != question_id or original_q.training_id != row.id:
            raise ApiError(409, "TRANSCRIPT_CONFLICT", "录音请求编号已用于其他内容")
        return {"transcript": {"id": old.id, "text": old.text, "seconds": old.seconds}}
    row = own_training(db, context.user.id, training_id, lock=True)
    from app.training_lease import require_writer
    require_writer(row, request.headers.get("X-Training-Lease"), context.session.id)
    q = current_question(db, row, question_id)
    if row.mode == "interview" and q.transcript_id:
        raise ApiError(409, "TRANSCRIPT_FINAL", "当前成功转写已固定，不能重新录音覆盖")
    if row.mode == "practice" and q.draft.strip() and not replace_confirmed:
        raise ApiError(409, "RECORDING_CONFIRMATION_REQUIRED", "请先确认替换未提交的复练草稿")
    step = f"asr:{q.id}:{hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]}"
    old_job = db.scalar(select(GenerationJob).where(GenerationJob.owner_id == context.user.id, GenerationJob.step_key == step))
    if old_job:
        raise ApiError(409, "ASR_REQUEST_HANDLED", "该录音正在处理或已失败，请查看当前题目后重试")
    previous_audio = list(db.scalars(select(GenerationJob).where(GenerationJob.training_id == row.id,
                                                               GenerationJob.kind == "asr")))
    attempts = [j for j in previous_audio if j.input_snapshot.get("question_id") == q.id
                and j.input_snapshot.get("audio_hash") == audio_hash]
    if len(attempts) >= 2 or any(j.state == "running" for j in attempts):
        raise ApiError(409, "ASR_RETRY_LIMIT", "同一录音仅允许失败后手动重试一次，请重新录音或使用键盘备用")
    job = GenerationJob(owner_id=context.user.id, training_id=row.id, kind="asr", step_key=step,
                        state="running", input_snapshot={"question_id": q.id, "audio_hash": audio_hash}, started_at=now_utc())
    db.add(job)
    db.commit()
    job_id = job.id
    original_revision = q.draft_revision
    def mark_failed(code, message):
        # A revoked request must not commit through its old authenticated session.
        # Only the private job outcome is written; no answer/draft is accepted here.
        with request.app.state.session_factory.begin() as background_db:
            failed_job = background_db.get(GenerationJob, job_id)
            if failed_job and failed_job.state == "running":
                failed_job.state, failed_job.error_code, failed_job.error_message = "failed", code, message
                failed_job.finished_at = now_utc()
    root = request.app.state.settings.speech_temporary_directory
    path = root / ("asr-" + job_id + ".audio")
    try:
        root.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)
        result = await run_in_threadpool(request.app.state.speech.transcribe, path)
        db.expire_all()
        fresh_authorization(db)
        row = own_training(db, context.user.id, training_id, lock=True)
        require_writer(row, request.headers.get("X-Training-Lease"), context.session.id)
        q = current_question(db, row, question_id)
        if q.draft_revision != original_revision:
            raise ApiError(409, "DRAFT_CONFLICT", "作答内容已更新，迟到转写未覆盖现有文字")
        if row.mode == "interview" and q.transcript_id:
            raise ApiError(409, "TRANSCRIPT_FINAL", "当前转写已固定，未覆盖原文")
        receipt = SpeechTranscript(owner_id=context.user.id, question_id=q.id, request_key=idempotency_key,
                                   audio_hash=audio_hash, text=result["text"], seconds=result["seconds"],
                                   provider=result["provider"])
        db.add(receipt)
        db.flush()
        q.transcript_id, q.draft, q.draft_revision = receipt.id, receipt.text, q.draft_revision + 1
        if row.mode == "interview":
            q.fault_id = q.keyboard_reason = None
        saved_job = db.get(GenerationJob, job_id)
        saved_job.state, saved_job.finished_at = "succeeded", now_utc()
        db.commit()
        return {"transcript": {"id": receipt.id, "text": receipt.text, "seconds": receipt.seconds}}
    except ApiError as error:
        db.rollback()
        mark_failed(error.code, error.message)
        raise
    except Exception:
        db.rollback()
        mark_failed("ASR_UNAVAILABLE", "转写暂不可用，请重新录音或使用键盘备用作答。")
        raise ApiError(503, "ASR_UNAVAILABLE", "转写暂不可用，请重新录音或使用键盘备用作答。") from None
    finally:
        path.unlink(missing_ok=True)


@router.get("/questions/{question_id}/audio")
def question_audio(question_id: str, request: Request, db: Db, context: Current):
    q = db.get(TrainingQuestion, question_id)
    if not q:
        raise ApiError(404, "QUESTION_NOT_FOUND", "题目不存在或不可访问")
    own_training(db, context.user.id, q.training_id)
    if q.asked_at is None:
        raise ApiError(404, "QUESTION_NOT_FOUND", "该题目尚未提问")
    hit_limit(db, "tts:" + context.user.id, 30, 60)
    path = request.app.state.speech.tts(q.text)
    return FileResponse(path, media_type="audio/wav", background=BackgroundTask(path.unlink, missing_ok=True))
