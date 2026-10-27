"""Operational metadata only: no model inputs, outputs or private training content."""
import re
import socket
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import case, func, select

from app.auth import Admin, Db
from app.config import BACKEND_DIR
from app.errors import ApiError
from app.model_budget import BudgetGuard, month_key
from app.models import GenerationJob, ModelSpend, Training, User, now_utc
from app.operation_diagnostics import diagnostic_view

router = APIRouter(prefix="/api/v1/admin", tags=["administration"])
PURPOSES = {"material_parse": "材料解析", "resume_parse": "简历解析", "jd_parse": "JD解析", "question": "面试出题", "followup": "追问", "report": "面试报告",
            "practice_feedback": "复练反馈", "integration_smoke": "接入测试"}


def spend_payload(row):
    return {"id": row.id, "purpose": row.purpose, "purposeLabel": PURPOSES.get(row.purpose, row.purpose),
            "model": row.model, "state": row.state, "createdAt": row.created_at.isoformat() + "Z",
            "durationMs": row.duration_ms, "promptTokens": row.prompt_tokens,
            "completionTokens": row.completion_tokens, "cachedTokens": row.cached_tokens,
            "chargedUpperMicroCny": row.charged_micro, "reservedMicroCny": row.reserved_micro,
            "feeSource": row.fee_source, "errorCode": row.error_code,
            "taskId": row.request_key.rsplit("-attempt-", 1)[0] if "-attempt-" in row.request_key else None}


def timestamp(value):
    return value.isoformat() + "Z" if value else None


def task_payload(row):
    return {"id": row.id, "kind": row.kind, "state": row.state, "attempts": row.attempts,
            "errorCode": row.error_code, "errorMessage": row.error_message,
            "createdAt": timestamp(row.created_at), "startedAt": timestamp(row.started_at),
            "finishedAt": timestamp(row.finished_at),
            "durationMs": max(0, int((row.finished_at - row.started_at).total_seconds() * 1000))
            if row.finished_at and row.started_at else None}


def call_detail(row):
    result = spend_payload(row)
    attempt = re.search(r"-attempt-(\d+)$", row.request_key)
    old_diagnostic = row.result.get("diagnostic") if isinstance(row.result, dict) and row.result.get("format") == "careerpilot-rejected-output-v1" else None
    result.update({"requestKey": row.request_key, "provider": row.provider,
                   "providerRequestId": row.provider_request_id, "attempt": int(attempt[1]) if attempt else None,
                   "finishedAt": timestamp(row.finished_at), "testMode": row.test_mode,
                   "totalTokens": row.prompt_tokens + row.completion_tokens
                   if row.prompt_tokens is not None and row.completion_tokens is not None else None,
                   "candidateAvailable": isinstance(row.result, dict) and row.result.get("format") == "careerpilot-rejected-output-v1",
                   "diagnostic": diagnostic_view(row.diagnostic or old_diagnostic, error_code=row.error_code)})
    return result


def operation_detail(db, task, *, selected=None):
    if task:
        condition = ModelSpend.request_key.startswith(task.id + "-attempt-", autoescape=True)
        rows = list(db.scalars(select(ModelSpend).where(condition).order_by(ModelSpend.created_at.desc(), ModelSpend.id).limit(100)))
        counts = db.execute(select(func.count(), func.coalesce(func.sum(ModelSpend.charged_micro), 0),
                           func.sum(case((ModelSpend.state == "unknown", 1), else_=0)))
                            .where(condition)).one()
        payload = {**task_payload(task), "trainingId": task.training_id,
                   "interviewPolicy": task.input_snapshot.get("interview_policy"),
                   "scoringVersion": (task.input_snapshot.get("scoring") or {}).get("version"),
                   "outputSaved": task.output is not None,
                   "diagnostic": diagnostic_view(task.diagnostic, error_code=task.error_code)}
        total, charged, unknown = counts
    else:
        rows = [selected] if selected else []
        payload = None
        total, charged, unknown = len(rows), sum(r.charged_micro or 0 for r in rows), sum(r.state == "unknown" for r in rows)
    if selected and all(row.id != selected.id for row in rows):
        rows = [selected, *rows[:99]]
    calls = [call_detail(row) for row in rows]
    return {"task": payload, "calls": calls, "callCount": total, "callsTruncated": total > len(calls),
            "chargedUpperMicroCny": charged, "unknownCallCount": unknown or 0,
            "selectedCallId": selected.id if selected else (calls[0]["id"] if calls else None),
            "observedAt": timestamp(now_utc())}


@router.get("/overview")
def overview(request: Request, db: Db, context: Admin):
    settings = request.app.state.settings
    now = now_utc()
    local = now + timedelta(hours=8)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    month_filter = ModelSpend.month_key == month_key()
    sent = db.scalar(select(func.count()).select_from(ModelSpend).where(month_filter,
                     ModelSpend.state.not_in(["reserved", "cancelled"])))
    succeeded = db.scalar(select(func.count()).select_from(ModelSpend).where(month_filter, ModelSpend.state == "succeeded"))
    finished = db.scalar(select(func.count()).select_from(ModelSpend).where(month_filter,
                         ModelSpend.state.in_(["succeeded", "failed", "unknown"])))
    unknown = db.scalar(select(func.count()).select_from(ModelSpend).where(month_filter, ModelSpend.state == "unknown"))
    try:
        with socket.create_connection((settings.smtp_host, settings.smtp_port), timeout=1):
            mail = "reachable"
    except OSError:
        mail = "unreachable"
    speech_ready = (settings.speech_model_directory / "model.bin").is_file() and (BACKEND_DIR / ".speech-deps" / "faster_whisper").is_dir()
    grouped = db.execute(select(ModelSpend.purpose, func.count(), func.sum(ModelSpend.charged_micro),
                         func.sum(ModelSpend.prompt_tokens), func.sum(ModelSpend.completion_tokens))
                         .where(month_filter, ModelSpend.state.not_in(["reserved", "cancelled"]))
                         .group_by(ModelSpend.purpose)).all()
    return {"userCount": db.scalar(select(func.count()).select_from(User).where(User.closed_at.is_(None))),
            "todayTraining": db.scalar(select(func.count()).select_from(Training).where(Training.started_at >= day_start)),
            "pendingJobs": db.scalar(select(func.count()).select_from(GenerationJob).where(GenerationJob.state.in_(["queued", "running", "ready", "paused"]))),
            "budgets": BudgetGuard(request.app.state.engine, settings).summary(),
            "successRate": round(100 * succeeded / finished, 2) if finished else None,
            "unknownCalls": unknown, "sentCalls": sent,
            "services": {"database": "ready", "email": mail, "speech": "installed" if speech_ready else "unavailable",
                         "model": "configured" if settings.deepseek_api_key else "unconfigured"},
            "allocations": [{"purpose": p, "label": PURPOSES.get(p, p), "calls": n,
                             "chargedUpperMicroCny": cost, "promptTokens": pt, "completionTokens": ct}
                            for p, n, cost, pt, ct in grouped], "updatedAt": now.isoformat() + "Z"}


@router.get("/tasks")
def tasks(db: Db, context: Admin, status: Literal["all", "succeeded", "failed", "pending"] = "all",
          offset: int = Query(0, ge=0), limit: int = Query(4, ge=1, le=100)):
    filters = []
    if status == "pending":
        filters.append(GenerationJob.state.in_(["queued", "running", "ready", "paused"]))
    elif status != "all":
        filters.append(GenerationJob.state == status)
    rows = list(db.scalars(select(GenerationJob).where(*filters).order_by(GenerationJob.created_at.desc(), GenerationJob.id)
                           .offset(offset).limit(limit)))
    return {"total": db.scalar(select(func.count()).select_from(GenerationJob).where(*filters)),
            "items": [task_payload(j) for j in rows]}


@router.get("/tasks/{task_id}")
def task_details(task_id: str, db: Db, context: Admin):
    task = db.get(GenerationJob, task_id)
    if not task:
        raise ApiError(404, "TASK_NOT_FOUND", "任务记录不存在或已清理")
    return operation_detail(db, task)


@router.get("/usage")
def usage(db: Db, context: Admin, purpose: str = Query("all", max_length=40),
          state: Literal["all", "succeeded", "failed", "unknown", "running", "reserved", "cancelled"] = "all",
          offset: int = Query(0, ge=0), limit: int = Query(4, ge=1, le=100)):
    filters = [ModelSpend.month_key == month_key()]
    if purpose != "all":
        filters.append(ModelSpend.purpose == purpose)
    if state != "all":
        filters.append(ModelSpend.state == state)
    rows = db.scalars(select(ModelSpend).where(*filters).order_by(ModelSpend.created_at.desc(), ModelSpend.id)
                      .offset(offset).limit(limit))
    return {"items": [spend_payload(row) for row in rows],
            "total": db.scalar(select(func.count()).select_from(ModelSpend).where(*filters))}


@router.get("/usage/{spend_id}")
def usage_details(spend_id: str, db: Db, context: Admin):
    spend = db.get(ModelSpend, spend_id)
    if not spend:
        raise ApiError(404, "CALL_NOT_FOUND", "调用记录不存在")
    task_id = spend_payload(spend)["taskId"]
    task = db.get(GenerationJob, task_id) if task_id else None
    return operation_detail(db, task, selected=spend)
