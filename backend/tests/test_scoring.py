from types import SimpleNamespace as NS

import pytest

from app.scoring import aggregate, is_abstention, snapshot, validate_ratings


def rubric():
    return snapshot({"role": "后端开发", "direction": "Python后端"})


def arrangement(count=3):
    rule = rubric()
    common = [d["id"] for d in rule["dimensions"][:3]]
    special = [d["id"] for d in rule["dimensions"][3:]]
    groups = [{"id": f"q{i}", "main": i, "dimension_ids": common + [special[(i - 1) % 3]]}
              for i in range(1, count + 1)]
    return rule, groups


def rating(group, level=3):
    return {"question_id": group["id"], "dimensions": [
        {"dimension_id": key, "level": level, "reason": "固定样例", "evidence": []}
        for key in group["dimension_ids"]]}


def test_approved_weights_and_all_seven_directions():
    cases = [("后端开发", "Python"), ("前端开发", "Vue"), ("软件测试", "功能测试"),
             ("软件测试", "测试开发"), ("AI 产品经理", "AI产品"),
             ("AI 应用开发", "大模型应用开发"), ("AI 应用开发", "Agent应用开发")]
    for role, direction in cases:
        frozen = snapshot({"role": role, "direction": direction})
        assert [d["weight"] for d in frozen["dimensions"]] == [15, 10, 15, 20, 20, 20]
        assert all(set(d["bands"]) == set("01234") for d in frozen["dimensions"])


def test_group_levels_average_before_fixed_dimension_weights():
    rule, groups = arrangement()
    result = aggregate(rule, groups, [rating(g, i + 2) for i, g in enumerate(groups)], 3)
    assert result["score"] == 75
    assert result["dimensions"][1]["score"] == 75
    assert result["evidenceCoverage"] == 100


def test_valid_zero_is_scored_and_covered_not_missing():
    rule, groups = arrangement()
    result = aggregate(rule, groups, [rating(g, 0) for g in groups], 3)
    assert result["state"] == "ready"
    assert result["score"] == 0
    assert result["scorableGroups"] == 3
    assert result["evidenceCoverage"] == 100


def test_early_end_keeps_whole_planned_denominator():
    rule, groups = arrangement(5)
    result = aggregate(rule, groups, [rating(g) for g in groups[:3]], 3)
    assert result["evidenceCoverage"] == 64
    assert result["score"] is None
    assert result["scorableGroups"] == 3
    assert result["completionPercent"] == 60


def test_missing_common_dimension_blocks_total_even_at_ninety_percent():
    rule, groups = arrangement()
    rows = [rating(g) for g in groups]
    for row in rows:
        row["dimensions"][1]["level"] = None
    result = aggregate(rule, groups, rows, 3)
    assert result["evidenceCoverage"] == 90
    assert result["score"] is None
    assert result["dimensions"][1]["score"] is None


def test_rounding_to_eighty_does_not_pass_exact_coverage_gate():
    rule = rubric()
    common = [d["id"] for d in rule["dimensions"][:3]]
    special = [d["id"] for d in rule["dimensions"][3:]]
    groups, rows = [], []
    for i in range(1, 9):
        assigned = [0, 1] if i <= 2 else [0, 2] if i <= 5 else [1, 2]
        group = {"id": f"q{i}", "main": i, "dimension_ids": common + [special[j] for j in assigned]}
        groups.append(group)
        row = rating(group)
        for item in row["dimensions"]:
            key = item["dimension_id"]
            if (key == common[0] and i == 8) or (key == common[1] and i > 2) or (key == special[1] and i == 8) or (key == special[2] and i > 6):
                item["level"] = None
        rows.append(row)
    result = aggregate(rule, groups, rows, 8)
    assert result["coverageFraction"] == [1919, 2400]
    assert result["evidenceCoverage"] == 80.0
    assert result["score"] is None
    assert len([d for d in result["dimensions"] if d["score"] is not None]) == 6


def sample_for_validation(text="我校验了接口权限并保留日志。"):
    rule, groups = arrangement()
    answers = [{"id": f"a{i}", "question_id": g["id"], "text": text, "skipped": False}
               for i, g in enumerate(groups)]
    result = NS(ratings=[NS(question_id=g["id"], dimensions=[
        NS(dimension_id=key, level=2, evidence=[NS(answer_id=a["id"], quote=text)])
        for key in g["dimension_ids"]]) for g, a in zip(groups, answers, strict=True)])
    return result, {"scoring": rule, "groups": groups, "questions": groups, "answers": answers}


def test_rating_evidence_cannot_cross_groups():
    result, data = sample_for_validation()
    result.ratings[0].dimensions[0].evidence[0].answer_id = "a1"
    with pytest.raises(ValueError, match="own group"):
        validate_ratings(result, data)


def test_only_dont_know_cannot_be_used_to_rate_any_dimension():
    result, data = sample_for_validation("我不知道。")
    with pytest.raises(ValueError, match="observable demonstration"):
        validate_ratings(result, data)


def test_no_experience_with_hypothetical_solution_is_still_evaluated():
    text = "没做过，但我会先明确权限，再用两个身份验证返回结果。"
    assert not is_abstention(text)
    result, data = sample_for_validation(text)
    validate_ratings(result, data)
