import time
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from test_training import RESUME, read, start, wait
from test_training import training as training
from training_support import FakeGateway

from app.models import GenerationJob, Material, MaterialFile, Training, TrainingAnswer, now_utc


def material_job(h, headers, source=RESUME):
    material = h.client.post('/api/v1/materials/resumes', content=source.encode(), params={'filename': 'private.txt'},
                            headers={**headers, 'Content-Type': 'application/octet-stream', 'Idempotency-Key': str(uuid4())}).json()['material']
    response = h.client.post(f'/api/v1/materials/resumes/{material["id"]}/model-parse',
                             json={'revision': material['revision']}, headers=headers)
    assert response.status_code == 202, response.text
    return material, response.json()['job']['id']


def wait_job(h, job_id, state='succeeded'):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = h.client.get(f'/api/v1/training/jobs/{job_id}').json()['job']
        if result['state'] == state:
            return result
        time.sleep(.02)
    raise AssertionError(f'Offline job did not reach {state}: {result}')


def test_model_material_organization_preserves_source_and_only_calls_once(h):
    fake = FakeGateway()
    h.app.state.generation.gateway_factory = lambda *_: fake
    h.register()
    headers = h.login()
    item, job_id = material_job(h, headers)
    wait_job(h, job_id)
    result = h.client.get(f'/api/v1/materials/resumes/{item["id"]}').json()['material']
    assert result['source'] == RESUME and result['parserVersion'] == 'material-source-ai-v1'
    assert result['status'] == 'pending' and result['fields']['projects'][0]['name'] == '材料服务'
    assert fake.calls == ['resume_parse']
    assert h.client.get(f'/api/v1/training/jobs/{job_id}').json()['job']['state'] == 'succeeded'
    assert fake.calls == ['resume_parse']


def test_late_model_parse_never_overwrites_confirmed_human_edits(h):
    fake = FakeGateway()
    fake.block = True
    h.app.state.generation.gateway_factory = lambda *_: fake
    h.register()
    headers = h.login()
    item, job_id = material_job(h, headers)
    assert fake.started.wait(3)
    fields = item['fields']
    fields['skills'] = '本人校对补充'
    fields['educations'] = [{'school': '第二所学校', 'major': '计算机', 'dates': '2024-2026'}]
    assert h.client.put(f'/api/v1/materials/resumes/{item["id"]}', json={'revision': item['revision'], 'fields': fields}, headers=headers).status_code == 200
    fake.release.set()
    wait_job(h, job_id, 'stale')
    result = h.client.get(f'/api/v1/materials/resumes/{item["id"]}').json()['material']
    assert result['fields']['skills'] == '本人校对补充' and result['status'] == 'confirmed'
    assert result['fields']['educations'][0]['school'] == '第二所学校'


def test_material_model_failure_keeps_original_and_manual_correction_available(h):
    fake = FakeGateway()
    fake.fail = 'MODEL_BUDGET_EXHAUSTED'
    h.app.state.generation.gateway_factory = lambda *_: fake
    h.register()
    headers = h.login()
    item, job_id = material_job(h, headers)
    job = wait_job(h, job_id, 'failed')
    result = h.client.get(f'/api/v1/materials/resumes/{item["id"]}').json()['material']
    assert result['source'] == RESUME and result['status'] == 'pending'
    assert result['parsingJob']['errorCode'] == 'MODEL_BUDGET_EXHAUSTED'
    assert h.client.put(f'/api/v1/materials/resumes/{item["id"]}', json={'revision': result['revision'], 'fields': result['fields']}, headers=headers).status_code == 200
    assert job['attempts'] == 1


def test_permanent_closure_revokes_sessions_retains_materials_and_cannot_be_reenabled(training):
    h, headers, resume_id, _, *_ = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    user_id = h.user().id
    response = h.client.post('/api/v1/account/close', json={'email': 'candidate@example.org', 'confirmed': True}, headers=headers)
    assert response.status_code == 200 and response.json()['retentionPolicy'] == 'closed_30_days'
    assert h.client.get('/api/v1/auth/me').status_code == 401
    assert h.client.post('/api/v1/auth/login', json={'email': 'candidate@example.org', 'password': 'Pilot-test-2026!'}).status_code == 401
    with h.app.state.session_factory() as db:
        material = db.get(Material, resume_id)
        assert material is not None and material.deleted_at is None
        assert db.get(MaterialFile, material.file_id) is not None
        assert db.get(Training, row['id']).status == 'interrupted'
    h.make_admin()
    admin_headers = h.login('admin@example.org')
    assert h.client.get(f'/api/v1/admin/users/{user_id}').json()['user']['closed'] is True
    assert h.client.patch(f'/api/v1/admin/users/{user_id}/status', json={'enabled': True}, headers=admin_headers).status_code == 409


def test_visible_answering_activity_is_bounded_idempotent_and_one_tab_at_a_time(training, monkeypatch):
    h, headers, *_ = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    now = [now_utc()]
    monkeypatch.setattr('app.training_api.now_utc', lambda: now[0])
    path = f'/api/v1/training/sessions/{row["id"]}/activity'
    lease = headers['X-Training-Lease']
    def pulse(n, active=True, elapsed=5000, lease_id=lease):
        return h.client.post(path, json={'lease': lease_id, 'sequence': n, 'elapsed_ms': elapsed, 'active': active}, headers=headers).json()
    assert pulse(1)['activeSeconds'] == 0
    now[0] += timedelta(seconds=5)
    assert pulse(2)['activeSeconds'] == 5
    assert pulse(2)['activeSeconds'] == 5
    rejected = h.client.post(path, json={'lease': str(uuid4()), 'sequence': 1, 'elapsed_ms': 0, 'active': True}, headers=headers)
    assert rejected.status_code == 409
    now[0] += timedelta(seconds=2)
    assert pulse(3, False)['activeSeconds'] == 7
    now[0] += timedelta(seconds=60)
    assert pulse(4)['activeSeconds'] == 7
    now[0] += timedelta(seconds=5)
    assert pulse(5)['activeSeconds'] == 12
    now[0] += timedelta(seconds=40)
    assert pulse(6)['activeSeconds'] == 12  # Missing heartbeats never count background time.


def test_admin_statistics_are_real_counts_and_exclude_private_job_payloads(training):
    h, *_ = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    assert h.client.get('/api/v1/admin/overview').status_code == 403
    h.make_admin()
    h.login('admin@example.org')
    snapshot = h.client.get('/api/v1/admin/overview').json()
    assert snapshot['todayTraining'] == 1 and snapshot['userCount'] == 2
    assert snapshot['successRate'] is None
    jobs = h.client.get('/api/v1/admin/tasks').json()['items']
    assert jobs[0]['id'] == row['jobs'][0]['id']
    assert not any(k in jobs[0] for k in ('input_snapshot', 'output', 'source', 'answer', 'owner_id'))
    users = h.client.get('/api/v1/admin/users', params={'q': 'candidate'}).json()['items']
    assert users[0]['interviews'] == 1 and users[0]['practices'] == 0
    with h.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(TrainingAnswer)) == 0


def test_abandoned_asr_is_recovered_without_generating_a_question_or_answer(training):
    h, _, _, _, fake, _ = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    with h.app.state.session_factory.begin() as db:
        job = GenerationJob(owner_id=h.user().id, training_id=row['id'], step_key='abandoned-local-asr', kind='asr',
                            state='running', input_snapshot={}, started_at=now_utc() - timedelta(minutes=10))
        db.add(job)
        db.flush()
        job_id = job.id
    result = h.client.get(f'/api/v1/training/jobs/{job_id}').json()['job']
    assert result['state'] == 'failed' and result['errorCode'] == 'SPEECH_INTERRUPTED'
    assert result['retryAllowed'] is False and fake.calls == ['question']
    assert read(training, row['id'])['answers'] == []


def test_unexpected_asr_failure_is_persisted_and_temporary_audio_is_removed(training):
    h, headers, *_ = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    def broken_transcribe(_):
        raise RuntimeError('synthetic internal failure; never expose provider internals')
    h.app.state.speech.transcribe = broken_transcribe
    response = h.client.post(f'/api/v1/training/sessions/{row["id"]}/transcripts', params={'question_id': row['currentQuestion']['id']},
                             content=b'audio-fixture', headers={**headers, 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 503 and 'synthetic internal failure' not in response.text
    result = read(training, row['id'])
    assert result['answers'] == [] and any(j['errorCode'] == 'ASR_UNAVAILABLE' and j['state'] == 'failed' for j in result['jobs'])
    assert not list(h.app.state.settings.speech_temporary_directory.glob('*.audio'))
