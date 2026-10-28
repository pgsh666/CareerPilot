import hashlib
import json

from sqlalchemy import select

from app.errors import ApiError
from app.interview_policy import interviewer_text
from app.models import (
    GenerationJob,
    Material,
    MaterialFile,
    MaterialVersion,
    PracticeTask,
    SpeechTranscript,
    Training,
    TrainingAnswer,
    TrainingQuestion,
    TrainingSlot,
    User,
    now_utc,
)
from app.training_prompts import model_context

TERMINAL = {"completed", "early_ended"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def lock_owner(db, owner_id):
    user = db.scalar(select(User).where(User.id == owner_id).with_for_update()
                     .execution_options(populate_existing=True))
    if not user or not user.enabled or user.closed_at:
        raise ApiError(403, "ACCOUNT_UNAVAILABLE", "当前账号不可用")
    return user


def slot_for(db, owner_id):
    slot = db.scalar(select(TrainingSlot).where(TrainingSlot.owner_id == owner_id).with_for_update())
    if not slot:
        slot = TrainingSlot(owner_id=owner_id)
        db.add(slot)
        db.flush()
    return slot


def own_training(db, owner_id, training_id, *, lock=False):
    if lock:
        lock_owner(db, owner_id)
        slot_for(db, owner_id)
    stmt = select(Training).where(Training.id == training_id, Training.owner_id == owner_id)
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if not row:
        raise ApiError(404, "TRAINING_NOT_FOUND", "训练不存在或不可访问")
    return row


def current_question(db, training, question_id=None, *, answering=True):
    if training.status != "active":
        raise ApiError(409, "TRAINING_NOT_ACTIVE", "训练已暂停或结束，请先继续训练")
    if answering and training.phase != "answering":
        raise ApiError(409, "QUESTION_NOT_ACCEPTING", "当前阶段不接受新的回答")
    if question_id and training.current_question_id != question_id:
        raise ApiError(409, "STALE_QUESTION", "题目已改变，旧录音或草稿未写入新题")
    question = db.get(TrainingQuestion, training.current_question_id)
    if not question:
        raise ApiError(409, "QUESTION_NOT_READY", "题目尚未准备完成")
    if answering and db.scalar(select(TrainingAnswer.id).where(TrainingAnswer.question_id == question.id)):
        raise ApiError(409, "ANSWER_ALREADY_ACCEPTED", "该题已经提交，不能覆盖原回答")
    return question


def freeze_material(db, owner_id, material_id, kind):
    row = db.scalar(select(Material).where(Material.id == material_id, Material.owner_id == owner_id,
                                          Material.kind == kind, Material.deleted_at.is_(None)))
    if not row or row.status != "confirmed" or not row.version:
        raise ApiError(409, "MATERIAL_NOT_CONFIRMED", "请选择本人已确认且未删除的简历和岗位JD")
    version = db.scalar(select(MaterialVersion).where(MaterialVersion.material_id == row.id,
                                                      MaterialVersion.number == row.version))
    if not version:
        raise ApiError(409, "MATERIAL_VERSION_MISSING", "材料确认版本暂不可用")
    snapshot = json.loads(json.dumps(version.snapshot))
    snapshot.update({"id": row.id, "version": row.version, "title": row.title})
    if row.file_id:
        file = db.get(MaterialFile, row.file_id)
        snapshot.update({"file": file.filename, "type": file.file_type})
    return snapshot


def make_job(db, training, kind, step, data):
    key = f"{training.id}:{step}"
    existing = db.scalar(select(GenerationJob).where(GenerationJob.owner_id == training.owner_id,
                                                    GenerationJob.step_key == key))
    if existing:
        return existing
    policy = (training.scoring_snapshot or {}).get("interviewPolicy")
    if policy:
        data = {**data, "interview_policy": policy}
    row = GenerationJob(owner_id=training.owner_id, training_id=training.id, kind=kind,
                        step_key=key, input_snapshot=data, auth_session_id=db.info.get("origin_session_id"))
    db.add(row)
    db.flush()
    return row


def active_replace(db, slot, replace_id, target_id=None):
    if not slot.training_id or slot.training_id == target_id:
        return
    old = db.get(Training, slot.training_id)
    if old and old.status not in TERMINAL:
        if replace_id != old.id:
            raise ApiError(409, "ACTIVE_TRAINING_EXISTS", "已有未结束训练，请确认替换后再开始")
        old.status, old.exit_reason = "interrupted", "replaced"
        old.writer_lease = old.writer_session_id = old.writer_seen_at = None
        old.activity_running = False
        old.updated_at = now_utc()
        old.revision += 1


def start_interview(db, owner_id, body, key):
    lock_owner(db, owner_id)
    slot = slot_for(db, owner_id)
    request_hash = digest(body.model_dump())
    old = db.scalar(select(Training).where(Training.owner_id == owner_id, Training.request_key == key))
    if old:
        if old.request_hash != request_hash:
            raise ApiError(409, "TRAINING_REQUEST_CONFLICT", "请求编号已用于其他训练内容")
        return old
    resume = freeze_material(db, owner_id, body.resume_id, "resume")
    job = freeze_material(db, owner_id, body.job_id, "job")
    active_replace(db, slot, body.replace_id)
    row = Training(owner_id=owner_id, request_key=key, request_hash=request_hash, mode="interview",
                   question_count=body.count, resume_snapshot=resume, job_snapshot=job)
    from app.scoring import snapshot
    try:
        row.scoring_snapshot = snapshot(job["fields"])
    except ValueError as error:
        raise ApiError(422, "ROLE_DIRECTION_UNSUPPORTED", str(error)) from None
    row.scoring_version = row.scoring_snapshot["version"]
    db.add(row)
    db.flush()
    slot.training_id = row.id
    from app.interview_policy import blueprint
    context = model_context(resume, job)
    make_job(db, row, "plan", "plan", {"count": body.count, "context": context,
                                     "scoring": row.scoring_snapshot,
                                     "interview_blueprint": blueprint(body.count, context)})
    db.commit()
    return row


def start_practice(db, owner_id, body, key):
    lock_owner(db, owner_id)
    slot = slot_for(db, owner_id)
    task = db.scalar(select(PracticeTask).where(PracticeTask.id == body.task_id, PracticeTask.owner_id == owner_id))
    if not task:
        raise ApiError(404, "PRACTICE_TASK_NOT_FOUND", "复练任务不存在或不可访问")
    old = db.scalar(select(Training).where(Training.owner_id == owner_id, Training.task_id == task.id,
                                         Training.status != "completed").order_by(Training.started_at.desc()))
    if old:
        return resume_training(db, owner_id, old.id, body.replace_id)
    request_hash = digest(body.model_dump())
    repeated = db.scalar(select(Training).where(Training.owner_id == owner_id, Training.request_key == key))
    if repeated:
        if repeated.request_hash != request_hash:
            raise ApiError(409, "TRAINING_REQUEST_CONFLICT", "请求编号已用于其他内容")
        return repeated
    source = db.get(Training, task.source_id)
    source_answer = db.get(TrainingAnswer, task.answer_id)
    active_replace(db, slot, body.replace_id)
    row = Training(owner_id=owner_id, request_key=key, request_hash=request_hash, mode="practice",
                   question_count=2, resume_snapshot=source.resume_snapshot, job_snapshot=source.job_snapshot,
                   task_id=task.id, source_id=source.id, original_answer=source_answer.text, phase="answering")
    row.scoring_version = source.scoring_version
    row.scoring_snapshot = source.scoring_snapshot
    db.add(row)
    db.flush()
    q = TrainingQuestion(training_id=row.id, main=1, follow=0, text=task.title,
                         topic=task.focus, basis=[], asked_at=now_utc())
    source_question = db.get(TrainingQuestion, task.question_id)
    q.dimension_ids, q.reference_points = source_question.dimension_ids, source_question.reference_points
    db.add(q)
    db.flush()
    row.current_question_id, slot.training_id = q.id, row.id
    db.commit()
    return row


def resume_training(db, owner_id, training_id, replace_id=None):
    row = own_training(db, owner_id, training_id, lock=True)
    if row.status == "completed" or (row.mode == "interview" and row.status == "early_ended"):
        raise ApiError(409, "TRAINING_FINISHED", "训练已结束，请查看本次结果")
    slot = slot_for(db, owner_id)
    active_replace(db, slot, replace_id, row.id)
    was_active = row.status == "active"
    row.status, row.exit_reason, row.finished_at = "active", None, None
    if not was_active:
        row.writer_lease = row.writer_session_id = row.writer_seen_at = None
    if row.mode == "practice" and row.phase == "finished":
        q = db.get(TrainingQuestion, row.current_question_id) if row.current_question_id else None
        answer = db.scalar(select(TrainingAnswer).where(TrainingAnswer.question_id == q.id)) if q else None
        if q and answer and answer.skipped:
            # Keep the skip receipt and resume the missing stage within the same practice.
            resumed_question = TrainingQuestion(training_id=row.id, main=q.main, follow=q.follow + 1,
                                                text=q.text, topic=q.topic, basis=q.basis, asked_at=now_utc())
            db.add(resumed_question)
            db.flush()
            row.current_question_id, q, answer = resumed_question.id, resumed_question, None
        variant = db.scalar(select(GenerationJob).where(GenerationJob.training_id == row.id,
                                                       GenerationJob.kind == "variant"))
        if variant and variant.state == "stale":
            variant.state = "ready" if variant.output is not None else "queued"
        row.phase = ("preparing" if variant and variant.state not in {"succeeded", "stale"}
                     else "feedback" if q and q.main == 1 and answer and answer.text else "answering")
    row.revision += 1
    row.updated_at = now_utc()
    slot.training_id = row.id
    db.commit()
    return row


def interrupt_active(db, owner_id, reason="logout"):
    # Used inside the logout transaction; the session revocation and interruption commit together.
    lock_owner(db, owner_id)
    slot = slot_for(db, owner_id)
    if slot.training_id:
        row = db.get(Training, slot.training_id)
        if row and row.status == "active":
            row.status, row.exit_reason, row.updated_at = "interrupted", reason, now_utc()
            row.activity_running = False
            row.writer_lease = row.writer_session_id = row.writer_seen_at = None
            row.revision += 1


def answer_payload(answer):
    return {"id": answer.id, "question_id": answer.question_id, "text": answer.text,
            "skipped": answer.skipped, "method": answer.method,
            "transcriptId": answer.transcript_id, "faultReason": answer.fault_reason,
            "rawTranscript": answer.raw_transcript,
            "createdAt": answer.created_at.isoformat() + "Z"}


def model_answer(answer):
    return {"id": answer.id, "question_id": answer.question_id, "text": answer.text, "skipped": answer.skipped}


def report_input(db, row):
    answers = list(db.scalars(select(TrainingAnswer).where(TrainingAnswer.training_id == row.id)
                              .order_by(TrainingAnswer.created_at, TrainingAnswer.id)))
    answered = {a.question_id for a in answers if a.text and not a.skipped}
    questions = list(db.scalars(select(TrainingQuestion).where(TrainingQuestion.training_id == row.id)
                               .order_by(TrainingQuestion.main, TrainingQuestion.follow)))
    answered_mains = {q.main for q in questions if q.id in answered}
    data = {"context": model_context(row.resume_snapshot, row.job_snapshot),
            "questions": [{"id": q.id, "text": q.text, "main": q.main, "follow": q.follow,
                           "reference_points": q.reference_points or [], "dimension_ids": q.dimension_ids or []}
                          for q in questions if q.id in answered or (q.follow == 0 and q.main in answered_mains)],
            "answers": [model_answer(a) for a in answers if a.text and not a.skipped]}
    if row.scoring_snapshot:
        data["scoring"] = row.scoring_snapshot
        data["groups"] = [{"id": q.id, "main": q.main, "dimension_ids": q.dimension_ids or [],
                           "reference_points": q.reference_points or []} for q in questions if q.follow == 0]
    return data


def finish_training(db, row, *, early=False):
    row.status, row.phase = ("early_ended" if early else "completed"), "finished"
    row.finished_at = row.updated_at = now_utc()
    row.activity_running = False
    row.writer_lease = row.writer_session_id = row.writer_seen_at = None
    row.revision += 1
    slot = slot_for(db, row.owner_id)
    if slot.training_id == row.id:
        slot.training_id = None
    if row.mode == "interview":
        data = report_input(db, row)
        if data["answers"]:
            row.report_state = "queued"
            make_job(db, row, "report", "report", data)
        else:
            row.report_state = "empty"
            row.report = {"summary": "尚未提交有效回答，暂无可评价内容。", "questions": [], "improvements": []}
            if row.scoring_snapshot and data.get("groups"):
                from app.scoring import aggregate
                row.report["scoring"] = aggregate(row.scoring_snapshot, data["groups"], [], 0)
    else:
        answers = list(db.scalars(select(TrainingAnswer).where(TrainingAnswer.training_id == row.id,
                                                               TrainingAnswer.skipped.is_(False))))
        if len([a for a in answers if a.text]) == 2:
            row.status = "completed"
            task = db.get(PracticeTask, row.task_id)
            task.done = True


def advance_main(db, row, current):
    if current.main >= row.question_count:
        finish_training(db, row)
        return
    nxt = db.scalar(select(TrainingQuestion).where(TrainingQuestion.training_id == row.id,
                                                  TrainingQuestion.main == current.main + 1,
                                                  TrainingQuestion.follow == 0))
    if not nxt:
        raise ApiError(409, "QUESTION_NOT_READY", "下一道主问题尚未准备完成")
    nxt.asked_at = nxt.asked_at or now_utc()
    row.current_question_id, row.phase = nxt.id, "answering"


def submit_answer(db, owner_id, training_id, body, key):
    row = own_training(db, owner_id, training_id, lock=True)
    fingerprint = digest(body.model_dump())
    accepted = db.scalar(select(TrainingAnswer).where(TrainingAnswer.question_id == body.question_id,
                                                      TrainingAnswer.training_id == row.id))
    if accepted:
        if accepted.request_key == key and accepted.fingerprint == fingerprint:
            return row
        raise ApiError(409, "ANSWER_ALREADY_ACCEPTED", "回答已保存，不能重复提交或修改")
    q = current_question(db, row, body.question_id)
    transcript = None
    if body.method == "skip":
        if not body.confirmed or body.text or body.transcript_id:
            raise ApiError(422, "SKIP_CONFIRMATION_REQUIRED", "请确认跳过本题，跳过不形成有效回答")
        text = ""
    elif body.method == "voice":
        transcript = db.scalar(select(SpeechTranscript).where(SpeechTranscript.id == body.transcript_id,
                                                                SpeechTranscript.owner_id == owner_id,
                                                                SpeechTranscript.question_id == q.id))
        if not transcript or q.transcript_id != transcript.id:
            raise ApiError(409, "TRANSCRIPT_REQUIRED", "请完成当前题目的真实语音转写")
        if row.mode == "interview" and body.text is not None:
            raise ApiError(422, "FORMAL_TRANSCRIPT_READONLY", "正式面试转写不可修改")
        text = transcript.text if row.mode == "interview" else (body.text if body.text is not None else transcript.text)
    else:
        if row.mode == "interview" and (not q.fault_id or q.fault_id != body.fault_id or q.transcript_id):
            raise ApiError(409, "KEYBOARD_NOT_AVAILABLE", "正式面试仅在当前题目语音故障时开放键盘作答")
        text = body.text or ""
        if body.transcript_id:
            transcript = db.scalar(select(SpeechTranscript).where(SpeechTranscript.id == body.transcript_id,
                                                                    SpeechTranscript.owner_id == owner_id,
                                                                    SpeechTranscript.question_id == q.id))
            if not transcript or row.mode != "practice":
                raise ApiError(409, "TRANSCRIPT_MISMATCH", "转写记录与本次复练不匹配")
    if body.method != "skip" and not text.strip():
        raise ApiError(422, "EMPTY_ANSWER", "回答不能为空")
    answer = TrainingAnswer(question_id=q.id, training_id=row.id, request_key=key,
                            fingerprint=fingerprint, text=text, skipped=body.method == "skip",
                            method=body.method, transcript_id=transcript.id if transcript else None,
                            fault_reason=q.keyboard_reason if body.method == "keyboard" else None)
    answer.raw_transcript = transcript.text if transcript else None
    db.add(answer)
    db.flush()  # The accepted answer is committed before any generation worker is scheduled.
    q.draft = ""
    q.draft_revision += 1
    row.revision += 1
    row.updated_at = now_utc()
    if (row.scoring_snapshot or {}).get("interviewPolicy"):
        from app.scoring import is_abstention
        abstained = is_abstention(text)
    else:
        abstained = any(x in text for x in ("不知道", "没有相关经历", "不了解", "没有做过"))
    if row.mode == "practice":
        if answer.skipped:
            finish_training(db, row, early=True)
        else:
            row.phase = "feedback"
            data = {"source_answer": row.original_answer, "question": q.text,
                    "answers": [model_answer(answer)], "main": q.main}
            make_job(db, row, "practice_feedback", f"feedback:{q.id}", data)
            if q.main == 2:
                finish_training(db, row)
    elif answer.skipped or q.follow >= 2 or abstained:
        advance_main(db, row, q)
    else:
        row.phase = "advancing"
        data = {"context": model_context(row.resume_snapshot, row.job_snapshot),
                "question": q.text, "follow": q.follow, "question_id": q.id,
                "answer": model_answer(answer)}
        if row.scoring_snapshot:
            data.update({"scoring": row.scoring_snapshot, "dimension_ids": q.dimension_ids,
                         "reference_points": q.reference_points})
        if (row.scoring_snapshot or {}).get("interviewPolicy"):
            group_questions = list(db.scalars(select(TrainingQuestion).where(
                TrainingQuestion.training_id == row.id, TrainingQuestion.main == q.main)
                .order_by(TrainingQuestion.follow)))
            group_answers = list(db.scalars(select(TrainingAnswer).where(
                TrainingAnswer.question_id.in_([question.id for question in group_questions]))))
            data["group_questions"] = [{"id": question.id, "text": question.text,
                                        "follow": question.follow,
                                        "reference_points": question.reference_points or []}
                                       for question in group_questions]
            data["group_answers"] = [model_answer(answer) for answer in group_answers]
        make_job(db, row, "advance", f"advance:{q.id}", data)
    db.commit()
    return row


def next_practice_stage(db, owner_id, training_id):
    row = own_training(db, owner_id, training_id, lock=True)
    q = db.get(TrainingQuestion, row.current_question_id)
    if row.mode != "practice" or row.status != "active" or not q or q.main != 1:
        raise ApiError(409, "PRACTICE_STAGE_INVALID", "当前复练不能切换阶段")
    answer = db.scalar(select(TrainingAnswer).where(TrainingAnswer.question_id == q.id))
    if not answer or answer.skipped or not answer.text:
        raise ApiError(409, "PRACTICE_ORIGINAL_REQUIRED", "请先实际提交原题重答")
    task = db.get(PracticeTask, row.task_id)
    row.phase = "preparing"
    make_job(db, row, "variant", "variant", {"focus": task.focus, "question": q.text,
                                               "answer": answer.text})
    db.commit()
    return row


def public_job(job):
    return {"id": job.id, "kind": job.kind, "state": job.state, "attempts": job.attempts,
            "errorCode": job.error_code, "errorMessage": job.error_message,
            "retryAllowed": job.kind not in {"asr", "tts"} and job.state == "failed" and job.error_code != "MODEL_COST_UNCERTAIN"}


def payload(db, row):
    questions = list(db.scalars(select(TrainingQuestion).where(TrainingQuestion.training_id == row.id,
                                                              TrainingQuestion.asked_at.is_not(None))
                                .order_by(TrainingQuestion.main, TrainingQuestion.follow)))
    q = db.get(TrainingQuestion, row.current_question_id) if row.current_question_id else None
    answers = list(db.scalars(select(TrainingAnswer).where(TrainingAnswer.training_id == row.id)
                              .order_by(TrainingAnswer.created_at, TrainingAnswer.id)))
    receipt = db.get(SpeechTranscript, q.transcript_id) if q and q.transcript_id else None
    jobs = list(db.scalars(select(GenerationJob).where(GenerationJob.training_id == row.id)
                           .order_by(GenerationJob.created_at)))
    computed = (row.report or {}).get("scoring", {})
    score_state = "rules_pending" if not row.scoring_snapshot else (
        computed.get("state") or {"queued": "generating", "failed": "failed", "empty": "insufficient_evidence"}.get(row.report_state, "not_requested"))
    return {"id": row.id, "mode": row.mode, "status": row.status, "phase": row.phase,
            "revision": row.revision, "count": row.question_count,
            "resume": row.resume_snapshot, "job": row.job_snapshot,
            "taskId": row.task_id, "sourceId": row.source_id, "sourceAnswer": row.original_answer,
            "currentQuestion": {"id": q.id, "text": interviewer_text(q.text), "main": q.main, "follow": q.follow,
                                "topic": q.topic, "draft": q.draft, "draftRevision": q.draft_revision,
                                "faultId": q.fault_id, "keyboardReason": q.keyboard_reason,
                                "transcriptId": q.transcript_id, "transcriptText": receipt.text if receipt else ""} if q else None,
            "questions": [{"id": x.id, "text": interviewer_text(x.text), "main": x.main, "follow": x.follow, "topic": x.topic,
                           **({"dimensionIds": x.dimension_ids, "referencePoints": x.reference_points}
                              if row.status in TERMINAL else {})} for x in questions],
            "answers": [answer_payload(a) for a in answers], "jobs": [public_job(j) for j in jobs],
            "feedback": row.feedback, "reportState": row.report_state, "report": row.report,
            "score": computed.get("score"), "scoreState": score_state, "scoreVersion": row.scoring_version,
            "evidenceCoverage": computed.get("evidenceCoverage"), "scoring": computed or None,
            "scoringRole": row.scoring_snapshot.get("roleKey") if row.scoring_snapshot else None,
            "activeSeconds": row.active_ms // 1000,
            "answeredMain": len({q2.main for q2 in questions for a in answers if a.question_id == q2.id and a.text and not a.skipped}),
            "startedAt": row.started_at.isoformat() + "Z",
            "finishedAt": row.finished_at.isoformat() + "Z" if row.finished_at else None}
