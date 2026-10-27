import json
from pathlib import Path

import pytest

from app.material_ai import prepare as prepare_material
from app.training_prompts import prepare


def captured_report():
    path = Path(__file__).with_name('fixtures') / 'report.json'
    return json.loads(path.read_text(encoding='utf-8'))


def report_contract():
    data = {'context': {}, 'questions': [{'id': 'synthetic-q1', 'main': 1, 'follow': 0}, {'id': 'synthetic-q2', 'main': 2, 'follow': 0}],
            'answers': [{'id': 'synthetic-a1', 'question_id': 'synthetic-q1', 'text': '这是合成练习项目，目标是帮助同学保存求职材料，我负责上传接口。', 'skipped': False},
                        {'id': 'synthetic-a2', 'question_id': 'synthetic-q2', 'text': '我先检查登录用户，再按用户ID查询文件；没有做过并发验证。', 'skipped': False}]}
    schema, _, _, validate = prepare('report', data)
    return schema, validate


def test_captured_real_report_keeps_evidence_and_one_priority_task_per_question():
    schema, validate = report_contract()
    report = schema.model_validate(captured_report(), strict=True)
    assert len(report.improvements) == 3
    validate(report)
    assert len(report.improvements) == 2 and len(report.questions) == 2
    assert report.improvements[1].focus == '越权防护说明'


def test_duplicate_task_with_fabricated_evidence_is_rejected_before_deduplication():
    schema, validate = report_contract()
    source = captured_report()
    source['improvements'][-1]['quote'] = '这句虚构的成果并未出现在回答中'
    with pytest.raises(ValueError, match='Evidence does not match'):
        validate(schema.model_validate(source, strict=True))


def test_material_model_cannot_invent_experience_or_enable_inferred_requirements():
    schema, _, _, validate = prepare_material({'kind': 'resume', 'source': '项目名称：材料服务\n个人职责：维护上传接口'})
    result = schema.model_validate({'fields': {'projects': [{'name': '不存在的高并发平台'}]}})
    with pytest.raises(ValueError, match='unsupported'):
        validate(result)
    schema, _, _, validate = prepare_material({'kind': 'job', 'source': '岗位名称：后端开发'})
    result = schema.model_validate({'fields': {'name': '后端开发', 'useInference': True}})
    with pytest.raises(ValueError, match='inference'):
        validate(result)
