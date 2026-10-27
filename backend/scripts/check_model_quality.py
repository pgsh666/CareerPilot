"""Two bounded synthetic checks, opt-in only; all spend uses the project lifetime ledger."""
import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / ".deps")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--real', action='store_true', help='At most two new synthetic requests; never automatic retry')
    parser.add_argument('--run-id', choices=['001', '002', '003', '004'], default='001', help='Explicit run ID; never automatically advanced')
    parser.add_argument('--calibration-only', action='store_true', help='Reuse saved plan; at most one new calibration request')
    args = parser.parse_args()
    if not args.real:
        raise SystemExit('No paid call made. Explicit --real is required.')
    from pydantic import BaseModel, ConfigDict, Field

    from app.config import Settings
    from app.db import make_engine
    from app.model_gateway import DeepSeekGateway
    from app.scoring import is_abstention, snapshot
    from app.training_prompts import SCORING_BOUNDARY, model_context, prepare

    class Dimension(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        id: str
        level: int | None = Field(ge=0, le=4)
        reason: str = Field(min_length=1, max_length=80)
        quote: str = Field(max_length=80)

    class Case(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        id: str
        dimensions: list[Dimension] = Field(min_length=4, max_length=4)

    class Batch(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        cases: list[Case] = Field(min_length=16, max_length=16)

        @classmethod
        def model_validate(cls, value, *args, **kwargs):
            # All content here is synthetic; keep rejected output for offline diagnosis.
            atomic_write(BACKEND.parent / 'artifacts' / 'prd-release' / 'calibration-candidate.json', value)
            return super().model_validate(value, *args, **kwargs)

    cases = json.loads(Path(__file__).with_name('quality_cases.json').read_text(encoding='utf-8'))['cases']
    definitions, inputs, expectations = {}, [], {}
    for case in cases:
        rubric = snapshot({'role': case['role'], 'direction': case['direction']})
        dims = rubric['dimensions'][:4]
        for dim in dims:
            definitions[dim['id']] = dim
        ids = [d['id'] for d in dims]
        inputs.append({k: case[k] for k in ('id', 'question', 'answer')} | {'dimensions': ids})
        expectations[case['id']] = dict(zip(ids, [case['expected'][d] for d in ('relevance', 'logic', 'evidence', 'special')], strict=True))
    # Expectations are not sent to the model, so they cannot be copied into the response.
    def validate(result):
        if len({c.id for c in result.cases}) != len(cases) or {c.id for c in result.cases} != set(expectations):
            raise ValueError('Case coverage mismatch')
        source = {c['id']: c for c in inputs}
        for result_case in result.cases:
            case = source[result_case.id]
            if {d.id for d in result_case.dimensions} != set(case['dimensions']):
                raise ValueError('Changed dimensions')
            for dim in result_case.dimensions:
                if dim.level is None:
                    if dim.quote:
                        raise ValueError('N/A has evidence')
                elif is_abstention(case['answer']) or not dim.quote or dim.quote not in case['answer']:
                    raise ValueError('Missing or invented evidence')
    settings = Settings()
    gateway = DeepSeekGateway(make_engine(settings), settings)
    destination = BACKEND.parent / 'artifacts' / 'prd-release'
    destination.mkdir(parents=True, exist_ok=True)
    report = {'format': 'careerpilot-quality-check-v1', 'humanReviewRequired': True,
              'scope': 'Synthetic expectations, tolerance 1 level; no expert certification or general accuracy claim',
              'plan': None, 'calibration': None, 'newCallsLimit': 1 if args.calibration_only else 2}
    try:
        # Exercise the real business plan contract, including locked dimensions and reference points.
        rubric = snapshot({'role': '后端开发', 'direction': 'Python'})
        context = model_context({'fields': {'skills': 'Python、MySQL', 'projects': [{'name': '材料服务',
                                'responsibility': '负责上传和权限接口', 'content': '为学生保存个人材料', 'result': '尚未上线，无真实性能数据'}]}},
                                {'fields': {'role': '后端开发', 'direction': 'Python', 'requirements': '接口设计、异常恢复、性能分析', 'useInference': False}})
        schema, system, content, validator = prepare('plan', {'count': 3, 'context': context, 'scoring': rubric})
        if args.calibration_only:
            report['plan'] = json.loads((destination / 'quality-plan.json').read_text(encoding='utf-8')) | {'reusedArtifact': True}
        else:
            print('Synthetic check 1/2: real three-question plan contract; no automatic retry.', flush=True)
            generated = gateway.generate(request_key='quality-v1-20261026-plan-' + args.run_id, purpose='question', system=system,
                                         content=content, schema=schema, validate=validator, policy_version='quality-plan-v1')
            report['plan'] = {'output': generated['output'].model_dump(), 'cached': generated['cached'],
                              'chargedUpperMicroCny': generated['chargedUpperMicroCny'], 'contractPassed': True}
            atomic_write(destination / 'quality-plan.json', report['plan'])
        prompt = ('你是CareerPilot固定规则校准评审。下面16份是合成回答，每份只评价指定4维。严格按给定0—4分档，不改变维度。'
                  '各维独立判断，专业错误不自动等于表达混乱；假设方案可凭推理和验证方法评分，不强求上线数据。'
                  '只说不知道或没做过且无任何实质内容时全部level=null且quote空。实质错误/泛泛内容按分档低分，不能用null规避。'
                  '必须逐一覆盖输入的16个case ID；每例dimensions为指定4个ID且不重复。'
                  '注意unknown和no-experience这两例均无实质分析，四维全部null，quote必须严格为字符串空串。'
                  '数值分必须给原答逐字短引文。每项reason尽量20字内，quote尽量15字内；不输出总分，不添加额外字段。'
                  + SCORING_BOUNDARY + '只输出JSON，契约：' + json.dumps(Batch.model_json_schema(), ensure_ascii=False))
        print('One calibration batch: seven directions x two answers, plus two N/A cases; no automatic retry.', flush=True)
        result = gateway.generate(request_key='quality-v1-20261026-calibration-' + args.run_id, purpose='report', system=prompt,
                                  content=json.dumps({'rules': list(definitions.values()), 'cases': inputs}, ensure_ascii=False),
                                  schema=Batch, validate=validate, max_output=8192, policy_version='quality-calibration-v1')
        checks = []
        for case in result['output'].cases:
            for dim in case.dimensions:
                expected = expectations[case.id][dim.id]
                passed = dim.level is None if expected is None else dim.level is not None and abs(dim.level - expected) <= 1
                checks.append({'case': case.id, 'dimension': dim.id, 'expected': expected, 'actual': dim.level, 'passed': passed})
        report['calibration'] = {'output': result['output'].model_dump(), 'checks': checks,
                                 'contractPassed': True, 'tolerancePassed': all(c['passed'] for c in checks),
                                 'cached': result['cached'], 'chargedUpperMicroCny': result['chargedUpperMicroCny']}
        report['passed'] = report['calibration']['tolerancePassed']
    except Exception as error:
        from app.errors import ApiError
        report['passed'] = False
        report['error'] = {'code': error.code if isinstance(error, ApiError) else type(error).__name__,
                           'message': error.message if isinstance(error, ApiError) else 'Check not completed; no automatic retry'}
    finally:
        report['budgets'] = gateway.guard.summary()
        atomic_write(destination / 'model-quality.json', report)
        print(json.dumps({'passed': report['passed'], 'error': report.get('error'),
                          'outsideTolerance': [c for c in (report.get('calibration') or {}).get('checks', []) if not c['passed']],
                          'testBudget': report['budgets']['test']}, ensure_ascii=False, indent=2))
    if not report['passed']:
        raise SystemExit(1)


def atomic_write(path, value):
    from app.maintenance_storage import atomic_json
    atomic_json(path, value)


if __name__ == '__main__':
    main()
