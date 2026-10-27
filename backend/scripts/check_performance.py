"""Single-user local MySQL/HTTP measurement. Exact synthetic rows are removed in finally."""
import json
import math
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from time import perf_counter

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / ".deps")]


def main():
    import httpx
    from sqlalchemy import delete
    from sqlalchemy.engine import make_url

    from app.config import Settings
    from app.db import make_engine, session_factory
    from app.models import (
        AuthSession,
        Training,
        TrainingAnswer,
        TrainingQuestion,
        User,
        new_id,
        now_utc,
    )
    from app.scoring import aggregate, snapshot
    from app.security import password_hasher

    settings = Settings()
    url = make_url(settings.database_url.get_secret_value())
    if settings.environment != "development" or url.host not in {"localhost", "127.0.0.1"} or url.database != "careerpilot_app":
        raise SystemExit("Only the dedicated local development database is accepted")
    engine = make_engine(settings)
    factory = session_factory(engine)
    owner_id = new_id()
    email = "performance-" + owner_id + "@example.org"
    password = secrets.token_urlsafe(24)
    fields = {"name": "性能合成岗位", "role": "后端开发", "direction": "Python", "requirements": "接口设计"}
    rubric = snapshot(fields)
    identifiers = [d["id"] for d in rubric["dimensions"]]
    training_ids, rows, qs, answers = [], [], [], []
    try:
        with factory.begin() as db:
            db.add(User(id=owner_id, email=email, name="性能合成用户", password_hash=password_hasher.hash(password)))
            db.flush()
            for i in range(100):
                training_id = new_id()
                training_ids.append(training_id)
                groups, ratings = [], []
                stamp = now_utc() - timedelta(minutes=100-i)
                for n in range(3):
                    qid, aid = new_id(), new_id()
                    dims = identifiers[:3] + [identifiers[3+n]]
                    groups.append({"id": qid, "main": n+1, "dimension_ids": dims})
                    ratings.append({"question_id": qid, "dimensions": [{"dimension_id": d, "level": 3,
                                   "reason": "性能数据，不用于专业评价", "evidence": [{"answer_id": aid, "quote": "合成作答"}]} for d in dims]})
                    qs.append(TrainingQuestion(id=qid, training_id=training_id, main=n+1, text="合成问题", topic="性能数据",
                              dimension_ids=dims, reference_points=["合成要点"], asked_at=stamp))
                    answers.append(TrainingAnswer(id=aid, question_id=qid, training_id=training_id, request_key=new_id(),
                                   fingerprint="synthetic", text="合成作答", method="keyboard", created_at=stamp))
                report = {"summary": "性能测试数据", "questions": [], "improvements": [], "scoring": aggregate(rubric, groups, ratings, 3)}
                rows.append(Training(id=training_id, owner_id=owner_id, request_key=new_id(), request_hash="synthetic", mode="interview",
                            status="completed", phase="ended", question_count=3, scoring_version=rubric["version"], scoring_snapshot=rubric,
                            resume_snapshot={"id": "performance-resume", "title": "合成简历", "version": 1, "fields": {}, "source": "合成原文"},
                            job_snapshot={"id": "performance-job", "title": "合成岗位", "version": 1, "fields": fields},
                            report=report, report_state="ready", started_at=stamp, finished_at=stamp, active_ms=60_000))
            db.add_all(rows)
            db.flush()
            db.add_all(qs)
            db.flush()
            db.add_all(answers)
        result = {"environment": "Windows/local MySQL/HTTP 8000, single user, warm connections", "syntheticRecords": 100,
                  "samplesPerEndpoint": 20, "modelCalls": 0, "measurements": []}
        with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", trust_env=False, timeout=10) as client:
            response = client.post('/auth/login', json={'email': email, 'password': password})
            response.raise_for_status()
            headers = {'X-CSRF-Token': response.json()['csrf_token']}
            paths = ['/auth/me', '/materials/resumes', '/materials/jobs', '/training/summary',
                     '/training/history?limit=10', '/training/filters', '/training/trend?days=0', '/training/sessions/' + training_ids[0], '/account/profile']
            for path in paths:
                durations, statuses = [], []
                for i in range(23):
                    before = perf_counter()
                    response = client.patch(path, headers=headers, json={'name': '性能合成用户'}) if path == '/account/profile' else client.get(path)
                    elapsed = (perf_counter() - before) * 1000
                    if i >= 3:
                        durations.append(elapsed)
                        statuses.append(response.status_code)
                p95 = sorted(durations)[math.ceil(.95 * len(durations)) - 1]
                result['measurements'].append({'endpoint': '/training/sessions/:id' if path.startswith('/training/sessions/') else path,
                     'method': 'PATCH' if path == '/account/profile' else 'GET', 'count': 20, 'p95Ms': round(p95, 2),
                     'maxMs': round(max(durations), 2), 'failures': sum(s != 200 for s in statuses), 'passed': p95 <= 1000 and all(s == 200 for s in statuses)})
        result['passed'] = all(r['passed'] for r in result['measurements'])
        destination = BACKEND.parent / 'artifacts' / 'prd-release' / 'performance.json'
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result['passed']:
            raise SystemExit(1)
    finally:
        with factory.begin() as db:
            if training_ids:
                db.execute(delete(TrainingAnswer).where(TrainingAnswer.training_id.in_(training_ids)))
                db.execute(delete(TrainingQuestion).where(TrainingQuestion.training_id.in_(training_ids)))
                db.execute(delete(Training).where(Training.id.in_(training_ids)))
            db.execute(delete(AuthSession).where(AuthSession.user_id == owner_id))
            db.execute(delete(User).where(User.id == owner_id))
        engine.dispose()


if __name__ == '__main__':
    main()
