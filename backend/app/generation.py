import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock

from sqlalchemy import select, update

from app.db import session_factory
from app.errors import ApiError
from app.model_gateway import DeepSeekGateway
from app.model_validation import diagnostic, rejected_output, safe_diagnostic
from app.models import (
    AuthSession,
    GenerationJob,
    ModelSpend,
    PracticeTask,
    Training,
    TrainingQuestion,
    User,
    now_utc,
)
from app.training_prompts import policy_version, prepare
from app.training_service import advance_main, own_training

logger = logging.getLogger("careerpilot")


def prepare_job(kind, data):
    if kind == "material_parse":
        from app.material_ai import prepare as prepare_material
        return prepare_material(data)
    return prepare(kind, data)


class GenerationRunner:
    def __init__(self, engine, settings, gateway_factory=None):
        self.engine, self.settings = engine, settings
        self.factory = session_factory(engine) if engine else None
        self.gateway_factory = gateway_factory or DeepSeekGateway
        self.pool = ThreadPoolExecutor(max_workers=settings.generation_workers, thread_name_prefix="careerpilot-job")
        self.lock = Lock()
        self.submitted = set()
        self.closed = False

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=True, cancel_futures=True)

    def schedule_training(self, training_id, auth_session_id=None):
        if not self.factory or self.closed:
            return
        with self.factory() as db:
            rows = list(db.scalars(select(GenerationJob).where(GenerationJob.training_id == training_id)))
        for row in rows:
            self.ensure(row.id, auth_session_id)

    def ensure(self, job_id, auth_session_id=None):
        if not self.factory or self.closed:
            return
        with self.factory.begin() as db:
            job = db.get(GenerationJob, job_id)
            if not job:
                return
            if job.state in {"succeeded", "stale"}:
                return
            if auth_session_id:
                auth = db.get(AuthSession, auth_session_id)
                if auth and auth.user_id == job.owner_id and not auth.revoked_at and auth.expires_at > now_utc():
                    job.auth_session_id = auth_session_id
            if job.kind in {"asr", "tts"}:
                if job.state == "running" and job.started_at and job.started_at < now_utc() - timedelta(seconds=self.settings.speech_timeout_seconds + 45):
                    job.state, job.error_code = "failed", "SPEECH_INTERRUPTED"
                    job.error_message, job.finished_at = "上次语音处理已中断，请重新录音或重播问题。", now_utc()
                return
            training = db.get(Training, job.training_id) if job.training_id else None
            if job.state == "ready" and training and training.status == "interrupted":
                return
            if job.state == "running" and job.started_at and job.started_at < now_utc() - timedelta(seconds=self.settings.model_timeout_seconds + 45):
                spend = db.scalar(select(ModelSpend).where(ModelSpend.request_key == self.call_key(job)))
                if spend is None or spend.state in {"reserved", "succeeded"}:
                    job.state = "queued"  # Same key: a known model result is reused, never repaid.
                else:
                    job.state, job.error_code = "failed", spend.error_code or "MODEL_COST_UNCERTAIN"
                    job.error_message = "上次任务未完成，已保留回答和费用记录，未自动重复调用。"
            if job.state == "paused":
                owner = db.get(User, job.owner_id)
                training = db.get(Training, job.training_id) if job.training_id else None
                auth = db.get(AuthSession, job.auth_session_id) if job.auth_session_id else None
                authorized = not job.auth_session_id or (auth and not auth.revoked_at and auth.expires_at > now_utc())
                allowed = owner and owner.enabled and not owner.closed_at and authorized and (not training or training.status != "interrupted")
                if allowed:
                    spend = db.scalar(select(ModelSpend).where(ModelSpend.request_key == self.call_key(job)))
                    if job.output is None and spend and spend.state == "cancelled" and spend.fee_source == "not_sent":
                        job.attempts += 1
                    job.state = "ready" if job.output is not None else "queued"
            schedule = job.state in {"queued", "ready"}
        if not schedule:
            return
        with self.lock:
            if job_id in self.submitted:
                return
            self.submitted.add(job_id)
        self.pool.submit(self._run, job_id)

    @staticmethod
    def call_key(job):
        return f"{job.id}-attempt-{job.attempts}"

    def _run(self, job_id):
        try:
            with self.factory.begin() as db:
                job = db.get(GenerationJob, job_id)
                if not job:
                    return
                if job.state == "ready":
                    only_apply = True
                else:
                    only_apply = False
                    changed = db.execute(update(GenerationJob).where(GenerationJob.id == job_id,
                                         GenerationJob.state == "queued").values(state="running", started_at=now_utc()),
                                         execution_options={"synchronize_session": False})
                    if changed.rowcount != 1:
                        return
                    owner = db.get(User, job.owner_id)
                    training = db.get(Training, job.training_id) if job.training_id else None
                    auth = db.get(AuthSession, job.auth_session_id) if job.auth_session_id else None
                    authorized = not job.auth_session_id or (auth and not auth.revoked_at and auth.expires_at > now_utc())
                    if not owner or not owner.enabled or owner.closed_at or not authorized or (training and training.status == "interrupted"):
                        db.execute(update(GenerationJob).where(GenerationJob.id == job_id).values(state="paused"))
                        return
                    if training and training.status in {"completed", "early_ended"} and job.kind not in {"report", "practice_feedback"}:
                        db.execute(update(GenerationJob).where(GenerationJob.id == job_id).values(state="stale"))
                        return
                    data, kind, owner_id, call_key = job.input_snapshot, job.kind, job.owner_id, self.call_key(job)
            if not only_apply:
                schema, prompt, content, validate = prepare_job(kind, data)
                result = self.gateway_factory(self.engine, self.settings).generate(
                    request_key=call_key, purpose=({"resume": "resume_parse", "job": "jd_parse"}[data["kind"]] if kind == "material_parse" else {"plan": "question", "advance": "followup", "variant": "question"}.get(kind, kind)),
                    system=prompt, content=content, schema=schema, owner_id=owner_id,
                    policy_version=policy_version(kind, data),
                    max_output=self.settings.model_report_max_output_tokens if kind == "report" and data.get("scoring") else None, validate=validate,
                )
                with self.factory.begin() as db:
                    job = db.get(GenerationJob, job_id)
                    if not job or job.state == "stale":
                        return  # Deleted/purged content must not be reintroduced by a late call.
                    job.output, job.state = result["output"].model_dump(mode="json"), "ready"
                    job.error_code = job.error_message = None
                    job.diagnostic = None
                    job.finished_at = now_utc()
            self.apply(job_id)
        except ApiError as error:
            self.fail(job_id, error.code, error.message, error.diagnostic)
        except Exception:
            logger.error("generation_failed job_id=%s", job_id)
            self.fail(job_id, "GENERATION_FAILED", "生成任务未完成，已保留材料与回答，请查看任务状态。",
                      {"stage": "worker", "rule": "GENERATION_FAILED"})
        finally:
            with self.lock:
                self.submitted.discard(job_id)

    def fail(self, job_id, code, message, detail=None):
        with self.factory.begin() as db:
            job = db.get(GenerationJob, job_id)
            if not job:
                return
            if job.state in {"succeeded", "stale"}:
                return
            if code in {"ACCOUNT_UNAVAILABLE", "SESSION_EXPIRED", "TRAINING_NOT_ACTIVE"}:
                job.state = "paused"
                return
            job.state, job.error_code, job.error_message = "failed", code, message[:200]
            job.diagnostic = safe_diagnostic(detail)
            job.finished_at = now_utc()
            if job.training_id and job.kind == "report":
                db.get(Training, job.training_id).report_state = "failed"

    def apply(self, job_id):
        with self.factory.begin() as db:
            initial = db.get(GenerationJob, job_id)
            if not initial or initial.state != "ready":
                return
            owner = db.scalar(select(User).where(User.id == initial.owner_id).with_for_update()
                              .execution_options(populate_existing=True))
            auth = db.scalar(select(AuthSession).where(AuthSession.id == initial.auth_session_id).with_for_update()
                             .execution_options(populate_existing=True)) if initial.auth_session_id else None
            authorized = not initial.auth_session_id or (auth and not auth.revoked_at and auth.expires_at > now_utc())
            if not owner or not owner.enabled or owner.closed_at or not authorized:
                initial.state = "paused"
                return
            if initial.kind == "material_parse":
                from app.material_ai import apply as apply_material
                apply_material(db, initial)
                return
            row = own_training(db, initial.owner_id, initial.training_id, lock=True)
            job = db.scalar(select(GenerationJob).where(GenerationJob.id == job_id).with_for_update()
                             .execution_options(populate_existing=True))
            if job.state != "ready":
                return
            if row.status == "interrupted":
                return  # Keep the result; resuming applies it without a second model request.
            if row.status in {"completed", "early_ended"} and job.kind not in {"report", "practice_feedback"}:
                job.state = "stale"
                return
            output = job.output
            db.info["origin_session_id"] = job.auth_session_id
            if job.kind == "plan":
                if row.current_question_id:
                    job.state = "stale"
                    return
                for main, item in enumerate(output["questions"], 1):
                    q = TrainingQuestion(training_id=row.id, main=main, follow=0,
                                         text=item["text"], topic=item["topic"], basis=item["basis"],
                                         asked_at=now_utc() if main == 1 else None)
                    if row.scoring_snapshot:
                        q.dimension_ids = [d["id"] for d in row.scoring_snapshot["dimensions"][:3]] + item["dimension_ids"]
                        q.reference_points = item["reference_points"]
                    db.add(q)
                    db.flush()
                    if main == 1:
                        row.current_question_id = q.id
                row.phase = "answering"
            elif job.kind == "advance":
                if row.current_question_id != job.input_snapshot["question_id"] or row.phase != "advancing":
                    job.state = "stale"
                    return
                q = db.get(TrainingQuestion, row.current_question_id)
                if output["action"] == "followup":
                    if q.follow >= 2:
                        raise ApiError(409, "FOLLOWUP_LIMIT", "本题组已达到两次追问上限")
                    nxt = TrainingQuestion(training_id=row.id, main=q.main, follow=q.follow + 1,
                                           text=output["question"], topic=q.topic,
                                           basis=[{"kind": "answer", "quote": output["quote"]}], asked_at=now_utc())
                    nxt.dimension_ids, nxt.reference_points = q.dimension_ids, output.get("reference_points")
                    db.add(nxt)
                    db.flush()
                    row.current_question_id, row.phase = nxt.id, "answering"
                else:
                    advance_main(db, row, q)
            elif job.kind == "report":
                if row.status not in {"completed", "early_ended"}:
                    job.state = "stale"
                    return
                if row.scoring_snapshot:
                    from app.scoring import aggregate
                    group_map = {q["id"]: q["main"] for q in job.input_snapshot["questions"]}
                    answered = len({group_map[a["question_id"]] for a in job.input_snapshot["answers"]})
                    output = {**output, "scoring": aggregate(row.scoring_snapshot, job.input_snapshot["groups"],
                                                             output["ratings"], answered)}
                row.report, row.report_state = output, "ready"
                for improvement in output["improvements"]:
                    existing = db.scalar(select(PracticeTask.id).where(PracticeTask.source_id == row.id,
                                                                        PracticeTask.question_id == improvement["question_id"]))
                    if not existing:
                        q = db.get(TrainingQuestion, improvement["question_id"])
                        db.add(PracticeTask(owner_id=row.owner_id, source_id=row.id, question_id=q.id,
                                            answer_id=improvement["answer_id"], title=q.text,
                                            focus=improvement["focus"], quote=improvement["quote"],
                                            suggestion=improvement["suggestion"]))
            elif job.kind == "practice_feedback":
                values = dict(row.feedback)
                values[str(job.input_snapshot["main"])] = output
                row.feedback = values
            elif job.kind == "variant":
                old = db.scalar(select(TrainingQuestion).where(TrainingQuestion.training_id == row.id,
                                                               TrainingQuestion.main == 2))
                if not old:
                    old = TrainingQuestion(training_id=row.id, main=2, follow=0, text=output["text"],
                                            topic=output["topic"], basis=output["basis"], asked_at=now_utc())
                    original = db.get(TrainingQuestion, row.current_question_id)
                    old.dimension_ids, old.reference_points = original.dimension_ids, original.reference_points
                    db.add(old)
                    db.flush()
                row.current_question_id, row.phase = old.id, "answering"
            else:
                raise ApiError(422, "UNKNOWN_JOB", "不支持的生成任务")
            row.revision += 1
            row.updated_at = now_utc()
            job.state = "succeeded"
            job.finished_at = now_utc()
        self.schedule_training(row.id)

    def retry(self, db, owner_id, job_id):
        job = db.get(GenerationJob, job_id)
        if not job or job.owner_id != owner_id:
            raise ApiError(404, "JOB_NOT_FOUND", "任务不存在或不可访问")
        if job.kind in {"asr", "tts"}:
            raise ApiError(409, "SPEECH_RETRY_REQUIRED", "请从当前题目重新录音或重播问题")
        if job.training_id:
            own_training(db, owner_id, job.training_id, lock=True)
        else:
            from app.training_service import lock_owner
            lock_owner(db, owner_id)
        db.refresh(job)
        if job.state != "failed":
            raise ApiError(409, "JOB_RETRY_LIMIT", "任务当前不能重复重试，请查看已有任务状态")
        spend = db.scalar(select(ModelSpend).where(ModelSpend.request_key == self.call_key(job)))
        if spend and spend.state in {"running", "unknown", "reserved"}:
            raise ApiError(409, "MODEL_COST_UNCERTAIN", "上次费用仍待核实，未发起新的付费调用")
        reusable = bool(spend and spend.state == "succeeded" and spend.result is not None)
        recovered = None
        recovered_spend = None
        candidates = [spend] if spend else []
        if job.kind == "report":
            candidates = list(db.scalars(select(ModelSpend).where(
                ModelSpend.owner_id == owner_id,
                ModelSpend.request_key.like(job.id + "-attempt-%"),
                ModelSpend.state == "failed", ModelSpend.error_code == "MODEL_OUTPUT_INVALID")
                .order_by(ModelSpend.created_at.desc(), ModelSpend.id).limit(20)))
        for cached in candidates:
            if cached.owner_id != owner_id or cached.state != "failed" or cached.error_code != "MODEL_OUTPUT_INVALID":
                continue
            candidate = rejected_output(cached.result)
            if candidate is not None:
                stage = "schema"
                try:
                    schema, _, _, validate = prepare_job(job.kind, job.input_snapshot)
                    recovered = schema.model_validate(candidate, strict=True)
                    if validate:
                        stage = "contract"
                        validate(recovered)
                    recovered_spend = cached
                    break
                except (ValueError, TypeError, KeyError, IndexError) as error:
                    recovered = None
                    logger.warning("cached_output_rejected job_id=%s diagnostic=%s", job.id,
                                   diagnostic(error, stage))
        reusable = reusable or recovered is not None
        job.state, job.error_code, job.error_message = "queued", None, None
        if not reusable:
            job.attempts += 1
        job.output, job.started_at, job.finished_at = None, None, None
        job.diagnostic = None
        if recovered is not None:
            job.output, job.state = recovered.model_dump(mode="json"), "ready"
            job.diagnostic = {"stage": "recovery", "rule": "CACHED_OUTPUT_ACCEPTED", "sourceSpendId": recovered_spend.id}
        job.auth_session_id = db.info.get("origin_session_id")
        if job.kind == "report":
            db.get(Training, job.training_id).report_state = "queued"
        db.commit()
        self.ensure(job.id)
        return job
