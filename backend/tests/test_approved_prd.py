"""Offline checks for confirmed rules, with isolated DB/files and no provider calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_training import completed_interview, read, start, wait
from test_training import training as training

from app.control_journal import load, record
from app.errors import ApiError
from app.maintenance import backup, cleanup, restore, verify_backup
from app.material_schemas import JobParse
from app.model_budget import BudgetGuard
from app.models import (
    GenerationJob,
    Material,
    MaterialFile,
    MaterialVersion,
    ModelSpend,
    SpeechTranscript,
    Training,
    User,
    VerificationCode,
    now_utc,
)


def test_takeover_rejects_old_tab_and_late_asr(training):
    h, headers, *_, speech = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    prefix = f'/api/v1/training/sessions/{row["id"]}'
    alternate = str(uuid4())
    response = h.client.post(prefix + '/lease', json={'lease': alternate}, headers=headers)
    assert response.json()['writable'] is False
    speech.block = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(lambda: h.client.post(prefix + '/transcripts', params={'question_id': row['currentQuestion']['id']},
                             content=b'late-audio', headers={**headers, 'Idempotency-Key': str(uuid4())}))
        assert speech.started.wait(3)
        assert h.client.post(prefix + '/lease', json={'lease': alternate, 'takeover': True}, headers=headers).json()['writable']
        speech.release.set()
        assert pending.result().status_code == 409
    assert read(training, row['id'])['writeAccess'] is False
    response = h.client.post(prefix + '/answers', json={'question_id': row['currentQuestion']['id'], 'method': 'skip', 'confirmed': True},
                             headers={**headers, 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 409
    with h.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(SpeechTranscript)) == 0
        assert db.scalar(select(GenerationJob).where(GenerationJob.kind == 'asr')).state == 'failed'


def test_lease_expires_at_thirty_seconds(training, monkeypatch):
    from app import training_lease
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    future = now_utc() + timedelta(seconds=31)
    monkeypatch.setattr(training_lease, 'now_utc', lambda: future)
    h, headers, *_ = training
    assert read(training, row['id'])['writeAccess'] is False
    other = h.client.post(f'/api/v1/training/sessions/{row["id"]}/lease', json={'lease': str(uuid4())}, headers=headers)
    assert other.json()['writable'] is True


def test_logout_during_asr_saves_only_private_failed_job(training):
    h, headers, *_, speech = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    speech.block = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(lambda: h.client.post(f'/api/v1/training/sessions/{row["id"]}/transcripts', params={'question_id': row['currentQuestion']['id']},
                             content=b'logout-audio', headers={**headers, 'Idempotency-Key': str(uuid4())}))
        assert speech.started.wait(3)
        assert h.client.post('/api/v1/auth/logout', headers=headers).status_code == 200
        speech.release.set()
        assert pending.result().status_code == 401
    with h.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(SpeechTranscript)) == 0
        assert db.scalar(select(GenerationJob).where(GenerationJob.kind == 'asr')).state == 'failed'


def test_deleted_resume_cleans_source_but_keeps_training_snapshot(training):
    h, headers, resume, *_ = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    settings, engine = h.app.state.settings, h.app.state.engine
    item = h.client.get(f'/api/v1/materials/resumes/{resume}').json()['material']
    assert h.client.request('DELETE', f'/api/v1/materials/resumes/{resume}', json={'revision': item['revision']}, headers=headers).status_code == 200
    assert cleanup(engine, settings)['materials'] == 1
    with h.app.state.session_factory() as db:
        material = db.get(Material, resume)
        assert material.file_id is None and not material.source and not material.fields
        assert db.scalar(select(func.count()).select_from(MaterialFile)) == 0
        assert db.scalar(select(func.count()).select_from(MaterialVersion).where(MaterialVersion.material_id == resume)) == 0
        assert db.get(Training, row['id']).resume_snapshot['source']
    assert cleanup(engine, settings)['materials'] == 0


def test_closed_account_purges_after_thirty_days_and_not_earlier(training):
    h, _, resume, *_ = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    user_id = h.user().id
    stamp = now_utc()
    with h.app.state.session_factory.begin() as db:
        user = db.get(User, user_id)
        user.closed_at, user.enabled = stamp, False
    assert cleanup(h.app.state.engine, h.app.state.settings, at=stamp + timedelta(days=29))['accounts'] == 0
    assert cleanup(h.app.state.engine, h.app.state.settings, at=stamp + timedelta(days=30))['accounts'] == 1
    with h.app.state.session_factory() as db:
        user = db.get(User, user_id)
        assert user.purged_at and user.former_email is None and user.password_hash == '!closed'
        assert db.get(Material, resume) is None and db.get(Training, row['id']) is None
        assert db.scalar(select(func.count()).select_from(VerificationCode).where(VerificationCode.email == 'candidate@example.org')) == 0
    assert load(h.app.state.settings, required=True)[0]['kind'] == 'account_closed'


def test_late_material_call_cannot_reintroduce_purged_source_or_cache(h):
    from test_training_integrity import material_job
    from training_support import FakeGateway
    fake = FakeGateway()
    fake.block = True
    h.app.state.generation.gateway_factory = lambda *_: fake
    h.register()
    headers = h.login()
    item, job_id = material_job(h, headers)
    assert fake.started.wait(3)
    guard = BudgetGuard(h.app.state.engine, h.app.state.settings)
    spend = guard.reserve(request_key=f'{job_id}-attempt-1', fingerprint='synthetic', owner_id=h.user().id,
                          purpose='resume_parse', model='deepseek-flash', maximum_micro=1000, pricing={})
    guard.dispatch(spend.id)
    response = h.client.request('DELETE', f'/api/v1/materials/resumes/{item["id"]}', json={'revision': item['revision']}, headers=headers)
    assert response.status_code == 200
    cleanup(h.app.state.engine, h.app.state.settings)
    guard.settle(spend.id, amount_micro=100, usage=(10, 10, 0), result={'private': 'deleted-source'},
                 error_code=None, duration_ms=1, provider_id='synthetic')
    fake.release.set()
    h.app.state.generation.close()
    with h.app.state.session_factory() as db:
        assert db.get(Material, item['id']).source == ''
        assert db.get(GenerationJob, job_id).state == 'stale'
        assert db.get(GenerationJob, job_id).output is None
        assert db.get(ModelSpend, spend.id).result is None
    assert guard.summary()['test']['chargedUpperMicroCny'] == 100


def reserve(guard, key):
    return guard.reserve(request_key=key, fingerprint=key, owner_id=None, purpose='report', model='deepseek-flash',
                         maximum_micro=1000, pricing={})


def test_restore_keeps_latest_fees_deletion_controls_and_revokes_logins(training, tmp_path):
    h, _, resume, *_ = training
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    settings = h.app.state.settings.model_copy(update={'backup_directory': tmp_path / 'backups'})
    engine = h.app.state.engine
    # Freeze queued work before this isolated destructive restore.
    h.app.state.generation.close()
    checkpoint = backup(engine, settings)
    manifest, _ = verify_backup(checkpoint['path'])
    assert manifest['tables']['users'] == 1
    guard = BudgetGuard(engine, settings)
    spend = reserve(guard, 'synthetic-restore-fee-001')
    guard.dispatch(spend.id)
    guard.settle(spend.id, amount_micro=700, usage=(10, 10, 0), result={'private': 'not-in-checkpoint'},
                 error_code=None, duration_ms=1, provider_id='synthetic')
    record(settings, 'material_deleted', resume)
    restored = restore(engine, settings, checkpoint['path'], confirmed_database=str(engine.url.database))
    assert restored['sessionsRevoked'] and guard.summary()['test']['chargedUpperMicroCny'] == 700
    with h.app.state.session_factory() as db:
        assert db.get(ModelSpend, spend.id).result is None
        assert db.get(Material, resume).status == 'purged'
        assert db.get(Training, row['id']).resume_snapshot['source']
    assert h.client.get('/api/v1/auth/me').status_code == 401


def test_restore_requires_latest_protection_and_checksums(h, tmp_path):
    settings = h.app.state.settings.model_copy(update={'backup_directory': tmp_path / 'backups'})
    result = backup(h.app.state.engine, settings)
    from app.control_journal import root_for
    (root_for(settings) / 'controls.jsonl').unlink()
    with pytest.raises(ApiError) as failure:
        restore(h.app.state.engine, settings, result['path'], confirmed_database=str(h.app.state.engine.url.database))
    assert failure.value.code == 'LATEST_CONTROLS_REQUIRED'
    from pathlib import Path
    Path(result['path']).write_bytes(b'corrupt')
    with pytest.raises(ApiError) as failure:
        verify_backup(result['path'])
    assert failure.value.code == 'BACKUP_INVALID'


def test_reconcile_unknown_fee_is_audited_and_idempotent(h):
    guard = BudgetGuard(h.app.state.engine, h.app.state.settings)
    spend = reserve(guard, 'synthetic-reconcile-fee-001')
    guard.dispatch(spend.id)
    guard.unknown(spend.id, 'MODEL_TIMEOUT', 60_000)
    assert guard.summary()['test']['heldMicroCny'] == 1000
    adjustment = guard.reconcile(spend.id, amount_micro=0, evidence_ref='supplier-confirmed-no-charge-001')
    assert not adjustment['reused'] and guard.summary()['test']['heldMicroCny'] == 0
    assert guard.reconcile(spend.id, amount_micro=0, evidence_ref='supplier-confirmed-no-charge-001')['reused']
    with pytest.raises(ApiError):
        guard.reconcile(spend.id, amount_micro=100, evidence_ref='supplier-confirmed-no-charge-001')


def test_crashed_dispatched_request_becomes_unknown_and_stays_held(h):
    guard = BudgetGuard(h.app.state.engine, h.app.state.settings)
    spend = reserve(guard, 'synthetic-orphan-fee-001')
    guard.dispatch(spend.id)
    cleanup(h.app.state.engine, h.app.state.settings,
            at=now_utc() + timedelta(seconds=h.app.state.settings.model_timeout_seconds + 46))
    with h.app.state.session_factory() as db:
        assert db.get(ModelSpend, spend.id).state == 'unknown'
    assert guard.summary()['test']['heldMicroCny'] == 1000
    assert not guard.reconcile(spend.id, amount_micro=0, evidence_ref='synthetic-confirmed-no-charge')['reused']


def test_jd_unicode_limit_normalizes_newlines_without_truncation():
    assert len(JobParse(source='😀' * 20000).source) == 20000
    assert JobParse(source='a\r\nb\rc').source == 'a\nb\nc'
    with pytest.raises(ValueError):
        JobParse(source='字' * 20001)


def test_same_email_reregisters_with_new_id_and_no_old_training(training, monkeypatch):
    from app import auth
    h, headers, *_ = training
    old = h.user()
    row = wait(training, start(training).json()['training']['id'], lambda r: r['phase'] == 'answering')
    assert h.client.post('/api/v1/account/close', json={'email': old.email, 'confirmed': True}, headers=headers).status_code == 200
    with h.app.state.session_factory() as db:
        original_closed = db.get(User, old.id).closed_at
    # The normal 60-second resend protection still applies; membership may be new immediately.
    later = now_utc() + timedelta(seconds=61)
    monkeypatch.setattr(auth, 'now_utc', lambda: later)
    fresh = h.register(old.email)
    assert fresh['id'] != old.id and fresh['role'] == 'user'
    h.login(old.email)
    assert h.client.get('/api/v1/training/history').json()['total'] == 0
    assert h.client.get(f'/api/v1/training/sessions/{row["id"]}').status_code == 404
    with h.app.state.session_factory() as db:
        assert db.get(User, old.id).closed_at == original_closed


def test_trend_filters_versions_and_never_changes_history(training):
    h = training[0]
    row = completed_interview(training)
    trend = h.client.get('/api/v1/training/trend?days=0').json()
    assert trend['sampleCount'] == 1 and len(trend['dimensions']) == 2
    assert trend['points'][0]['values'] == [75, 75]
    assert trend['group']['target'] == f'{row["job"]["id"]}-v{row["job"]["version"]}'
    assert h.client.get('/api/v1/training/trend?scoring_version=absent').json()['sampleCount'] == 0
    assert h.client.get('/api/v1/training/history').json()['total'] == 1
