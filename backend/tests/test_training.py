import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from training_support import FakeGateway, FakeSpeech

from app.models import SpeechTranscript, TrainingAnswer

RESUME = "姓名：训练用户\n项目名称：材料服务\n个人职责：维护上传接口\n专业技能：Python、MySQL"
JD = "岗位名称：后端开发工程师\n岗位方向：Python\n岗位职责：开发接口\n任职要求：熟悉Python与MySQL"


@pytest.fixture
def training(h):
    fake, speech = FakeGateway(), FakeSpeech()
    h.app.state.generation.gateway_factory = lambda *_: fake
    h.app.state.speech = speech
    h.register()
    headers = h.login()
    uploaded = h.client.post("/api/v1/materials/resumes", params={"filename": "mine.txt"},
                             content=RESUME.encode(), headers={**headers, "Content-Type": "application/octet-stream", "Idempotency-Key": str(uuid4())}).json()["material"]
    saved = h.client.put(f'/api/v1/materials/resumes/{uploaded["id"]}', json={"revision": uploaded["revision"], "fields": uploaded["fields"]}, headers=headers)
    assert saved.status_code == 200
    job = h.client.post("/api/v1/materials/jobs", json={"source": JD}, headers={**headers, "Idempotency-Key": str(uuid4())}).json()["material"]
    fields = {k: job[k] for k in ("name", "company", "role", "direction", "responsibilities", "requirements", "inference", "useInference")}
    assert h.client.put(f'/api/v1/materials/jobs/{job["id"]}', json={"revision": job["revision"], "source": JD, "fields": fields}, headers=headers).status_code == 200
    return h, headers, uploaded["id"], job["id"], fake, speech


def start(t, *, key=None, replace_id=None):
    h, headers, resume, job, *_ = t
    result = h.client.post("/api/v1/training/interviews", json={"resume_id": resume, "job_id": job,
                          "count": 3, "confirmed": True, "replace_id": replace_id},
                          headers={**headers, "Idempotency-Key": key or str(uuid4())})
    if result.status_code == 201:
        acquire_writer(t, result.json()["training"]["id"])
    return result


def acquire_writer(t, training_id):
    h, headers, *_ = t
    # The fixture has one browser tab; multi-tab tests explicitly acquire a different lease.
    headers.setdefault("X-Training-Lease", str(uuid4()))
    return h.client.post(f"/api/v1/training/sessions/{training_id}/lease",
                         json={"lease": headers["X-Training-Lease"]}, headers=headers)


def read(t, training_id):
    return t[0].client.get(f"/api/v1/training/sessions/{training_id}", headers=t[1]).json()["training"]


def wait(t, training_id, condition):
    # Login may have rotated the CSRF token, so refresh it from the current valid session.
    current = t[0].client.get("/api/v1/auth/me")
    if current.status_code == 200:
        t[1]["X-CSRF-Token"] = current.json()["csrf_token"]
        acquire_writer(t, training_id)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        row = read(t, training_id)
        if condition(row):
            return row
        time.sleep(0.02)
    raise AssertionError("Offline training job did not reach the expected state")


def keyboard(t, row, text, key=None):
    h, headers, *_ = t
    q = row["currentQuestion"]
    fault = h.client.post(f'/api/v1/training/sessions/{row["id"]}/speech-fault',
                          json={"question_id": q["id"], "reason": "browser_unsupported"}, headers=headers).json()
    return h.client.post(f'/api/v1/training/sessions/{row["id"]}/answers',
                         json={"question_id": q["id"], "method": "keyboard", "text": text,
                               "fault_id": fault["faultId"]}, headers={**headers, "Idempotency-Key": key or str(uuid4())})


def test_interview_plan_is_idempotent_and_unasked_questions_are_not_exposed(training):
    key = str(uuid4())
    first = start(training, key=key)
    assert first.status_code == 201
    row = wait(training, first.json()["training"]["id"], lambda x: x["phase"] == "answering")
    assert len(row["questions"]) == 1 and row["currentQuestion"]["main"] == 1
    assert start(training, key=key).json()["training"]["id"] == row["id"]
    assert training[4].calls == ["question"]
    assert row["score"] is None and row["scoreState"] == "not_requested"
    assert row["scoreVersion"] == "careerpilot-rubric-v1-interview-v2"
    assert "referencePoints" not in row["questions"][0]
    assert start(training).status_code == 409
    second = start(training, replace_id=row["id"]).json()["training"]
    assert second["id"] != row["id"]
    assert read(training, row["id"])["status"] == "interrupted"


def test_logout_restores_same_question_draft_and_frozen_material(training):
    h, headers, resume_id, _, fake, _ = training
    row = wait(training, start(training).json()["training"]["id"], lambda x: x["phase"] == "answering")
    q = row["currentQuestion"]
    h.client.post(f'/api/v1/training/sessions/{row["id"]}/speech-fault', json={"question_id": q["id"], "reason": "permission_denied"}, headers=headers)
    assert h.client.put(f'/api/v1/training/sessions/{row["id"]}/draft', json={"question_id": q["id"], "revision": 1, "text": "尚未提交的本人草稿"}, headers=headers).status_code == 200
    resume = h.client.get("/api/v1/materials/resumes").json()["items"][0]
    resume["fields"]["skills"] = "更新后的材料"
    h.client.put(f"/api/v1/materials/resumes/{resume_id}", json={"revision": resume["revision"], "fields": resume["fields"]}, headers=headers)
    assert h.client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    headers2 = h.login()
    before = read(training, row["id"])
    assert before["status"] == "interrupted"
    restored = h.client.post(f'/api/v1/training/sessions/{row["id"]}/resume', json={}, headers=headers2).json()["training"]
    assert restored["currentQuestion"]["id"] == q["id"]
    assert restored["currentQuestion"]["draft"] == "尚未提交的本人草稿"
    assert restored["resume"]["fields"]["skills"] == "Python、MySQL"
    assert fake.calls == ["question"]


def test_generation_finishing_after_logout_is_reused_on_resume(training):
    h, headers, _, _, fake, _ = training
    fake.block = True
    row = start(training).json()["training"]
    assert fake.started.wait(3)
    h.client.post("/api/v1/auth/logout", headers=headers)
    fake.release.set()
    headers2 = h.login()
    paused = wait(training, row["id"], lambda x: any(j["state"] in {"ready", "paused"} for j in x["jobs"]))
    assert paused["currentQuestion"] is None
    h.client.post(f'/api/v1/training/sessions/{row["id"]}/resume', json={}, headers=headers2)
    restored = wait(training, row["id"], lambda x: x["phase"] == "answering")
    assert restored["currentQuestion"]["main"] == 1 and fake.calls == ["question"]


def test_formal_voice_is_canonical_and_duplicate_answer_cannot_replace_it(training):
    h, headers, *_ = training
    row = wait(training, start(training).json()["training"]["id"], lambda x: x["phase"] == "answering")
    q = row["currentQuestion"]
    prefix = f'/api/v1/training/sessions/{row["id"]}'
    assert h.client.post(prefix + "/answers", json={"question_id": q["id"], "method": "keyboard", "text": "擅自键盘作答"}, headers={**headers, "Idempotency-Key": str(uuid4())}).status_code == 409
    receipt = h.client.post(prefix + "/transcripts", params={"question_id": q["id"]}, content=b"isolated-audio-fixture", headers={**headers, "Idempotency-Key": str(uuid4())}).json()["transcript"]
    assert h.client.post(prefix + "/speech-fault", json={"question_id": q["id"], "reason": "recording_failed"}, headers=headers).status_code == 409
    assert h.client.post(prefix + "/answers", json={"question_id": q["id"], "method": "voice", "transcript_id": receipt["id"], "text": "修改转写"}, headers={**headers, "Idempotency-Key": str(uuid4())}).status_code == 422
    key = str(uuid4())
    body = {"question_id": q["id"], "method": "voice", "transcript_id": receipt["id"]}
    assert h.client.post(prefix + "/answers", json=body, headers={**headers, "Idempotency-Key": key}).status_code == 200
    assert h.client.post(prefix + "/answers", json=body, headers={**headers, "Idempotency-Key": key}).status_code == 200
    assert h.client.post(prefix + "/answers", json={**body, "text": "晚到篡改"}, headers={**headers, "Idempotency-Key": str(uuid4())}).status_code == 409
    with h.app.state.session_factory() as db:
        answers = list(db.scalars(select(TrainingAnswer)))
        assert len(answers) == 1 and answers[0].text == receipt["text"]


def test_followups_are_limited_to_two_and_skip_never_creates_answer_text(training):
    h, headers, *_ = training
    row = wait(training, start(training).json()["training"]["id"], lambda x: x["phase"] == "answering")
    for follow in range(3):
        assert row["currentQuestion"]["follow"] == follow
        assert keyboard(training, row, "请继续追问，我负责权限验证。").status_code == 200
        row = wait(training, row["id"], lambda x: x["phase"] == "answering")
    assert row["currentQuestion"]["main"] == 2 and row["currentQuestion"]["follow"] == 0
    old_id = row["currentQuestion"]["id"]
    body = {"question_id": old_id, "method": "skip", "confirmed": True}
    skipped = h.client.post(f'/api/v1/training/sessions/{row["id"]}/answers', json=body, headers={**headers, "Idempotency-Key": str(uuid4())}).json()["training"]
    assert skipped["currentQuestion"]["main"] == 3
    assert next(a for a in skipped["answers"] if a["question_id"] == old_id)["text"] == ""


def test_late_asr_after_skip_cannot_write_to_any_question(training):
    h, headers, _, _, _, speech = training
    row = wait(training, start(training).json()["training"]["id"], lambda x: x["phase"] == "answering")
    prefix = f'/api/v1/training/sessions/{row["id"]}'
    speech.block = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(lambda: h.client.post(prefix + "/transcripts", params={"question_id": row["currentQuestion"]["id"]}, content=b"late-audio", headers={**headers, "Idempotency-Key": str(uuid4())}))
        assert speech.started.wait(3)
        h.client.post(prefix + "/answers", json={"question_id": row["currentQuestion"]["id"], "method": "skip", "confirmed": True}, headers={**headers, "Idempotency-Key": str(uuid4())})
        speech.release.set()
        assert pending.result().status_code == 409
    with h.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(SpeechTranscript)) == 0


def test_failed_generation_preserves_accepted_answer_and_explicit_retry_is_bounded(training):
    h, headers, _, _, fake, _ = training
    row = wait(training, start(training).json()["training"]["id"], lambda x: x["phase"] == "answering")
    fake.fail = "MODEL_OUTPUT_INVALID"
    assert keyboard(training, row, "这是已接受的回答，需要保留。").status_code == 200
    failed = wait(training, row["id"], lambda x: any(j["state"] == "failed" for j in x["jobs"]))
    assert failed["answers"][0]["text"] == "这是已接受的回答，需要保留。"
    job = next(j for j in failed["jobs"] if j["state"] == "failed")
    assert job["retryAllowed"]
    fake.fail = None
    assert h.client.post(f'/api/v1/training/jobs/{job["id"]}/retry', json={"confirmed": True}, headers=headers).status_code == 200
    wait(training, row["id"], lambda x: x["phase"] == "answering")
    assert h.client.post(f'/api/v1/training/jobs/{job["id"]}/retry', json={"confirmed": True}, headers=headers).status_code == 409


def completed_interview(t):
    row = wait(t, start(t).json()["training"]["id"], lambda x: x["phase"] == "answering")
    for _ in range(3):
        assert keyboard(t, row, "我说明了项目背景，但不了解这个具体细节。").status_code == 200
        row = wait(t, row["id"], lambda x: x["phase"] in {"answering", "finished"})
    return wait(t, row["id"], lambda x: x["reportState"] == "ready")


def test_report_evidence_and_two_stage_practice_preserve_source_answer(training):
    h, headers, *_ = training
    row = completed_interview(training)
    assert row["status"] == "completed" and row["score"] == 75
    assert row["scoreState"] == "ready" and row["evidenceCoverage"] == 100
    summary = h.client.get("/api/v1/training/summary").json()
    assert summary["completedInterviews"] == 1 and len(summary["tasks"]) == 1
    task = summary["tasks"][0]
    practice = h.client.post("/api/v1/training/practices", json={"task_id": task["id"]}, headers={**headers, "Idempotency-Key": str(uuid4())}).json()["training"]
    acquire_writer(training, practice["id"])
    prefix = f'/api/v1/training/sessions/{practice["id"]}'
    q = practice["currentQuestion"]
    receipt = h.client.post(prefix + "/transcripts", params={"question_id": q["id"]}, content=b"practice-audio", headers={**headers, "Idempotency-Key": str(uuid4())}).json()["transcript"]
    submitted = "复练允许修改后的最终提交文字。"
    response = h.client.post(prefix + "/answers", json={"question_id": q["id"], "method": "voice", "transcript_id": receipt["id"], "text": submitted}, headers={**headers, "Idempotency-Key": str(uuid4())})
    assert response.status_code == 200
    first = wait(training, practice["id"], lambda x: bool(x["feedback"].get("1")))
    assert first["answers"][0]["rawTranscript"] == receipt["text"]
    assert first["answers"][0]["text"] == submitted
    assert not h.client.get("/api/v1/training/summary").json()["tasks"][0]["done"]
    assert h.client.post(prefix + "/next-stage", json={"confirmed": True}, headers=headers).status_code == 200
    variant = wait(training, practice["id"], lambda x: x["phase"] == "answering")
    assert variant["currentQuestion"]["main"] == 2 and variant["sourceAnswer"] == practice["sourceAnswer"]
    assert keyboard(training, variant, "变式的实际提交文字。").status_code == 200
    done = wait(training, practice["id"], lambda x: bool(x["feedback"].get("2")))
    assert done["status"] == "completed"
    assert h.client.get("/api/v1/training/summary").json()["tasks"][0]["done"]
    assert read(training, row["id"])["answers"][0]["text"] == practice["sourceAnswer"]


def test_training_questions_and_jobs_cannot_be_read_by_another_user(training):
    h = training[0]
    row = wait(training, start(training).json()["training"]["id"], lambda x: x["phase"] == "answering")
    h.register("other-training@example.org")
    h.login("other-training@example.org")
    assert h.client.get(f'/api/v1/training/sessions/{row["id"]}').status_code == 404
    assert h.client.get(f'/api/v1/training/jobs/{row["jobs"][0]["id"]}').status_code == 404
    assert h.client.get(f'/api/v1/training/questions/{row["currentQuestion"]["id"]}/audio').status_code == 404
    assert h.client.get("/api/v1/training/history").json()["total"] == 0


def test_skipped_practice_resumes_missing_stage_in_same_record_and_preserves_skip(training):
    h, headers, *_ = training
    completed_interview(training)
    task = h.client.get('/api/v1/training/summary').json()['tasks'][0]
    practice = h.client.post('/api/v1/training/practices', json={'task_id': task['id']},
                             headers={**headers, 'Idempotency-Key': str(uuid4())}).json()['training']
    acquire_writer(training, practice['id'])
    prefix = f'/api/v1/training/sessions/{practice["id"]}'
    skipped_id = practice['currentQuestion']['id']
    response = h.client.post(prefix + '/answers', json={'question_id': skipped_id, 'method': 'skip', 'confirmed': True},
                             headers={**headers, 'Idempotency-Key': str(uuid4())})
    assert response.json()['training']['status'] == 'early_ended'
    resumed = h.client.post(prefix + '/resume', json={}, headers=headers).json()['training']
    acquire_writer(training, resumed['id'])
    assert resumed['id'] == practice['id'] and resumed['currentQuestion']['main'] == 1
    assert resumed['currentQuestion']['id'] != skipped_id
    assert any(a['skipped'] and a['question_id'] == skipped_id for a in resumed['answers'])
    assert keyboard(training, resumed, '原题这次实际提交的回答。').status_code == 200
    assert h.client.post(prefix + '/next-stage', json={'confirmed': True}, headers=headers).status_code == 200
    variant = wait(training, practice['id'], lambda x: x['currentQuestion']['main'] == 2)
    assert keyboard(training, variant, '这次是变式的实际回答。').status_code == 200
    done = read(training, practice['id'])
    assert done['status'] == 'completed' and len(done['answers']) == 3
    assert h.client.get('/api/v1/training/summary').json()['tasks'][0]['done']
