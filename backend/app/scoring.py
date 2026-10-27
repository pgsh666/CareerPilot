"""Approved v1 rubric and deterministic aggregation; the model never calculates totals."""
import json
import re
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from app.interview_policy import VERSION as INTERVIEW_POLICY

RULES = json.loads(Path(__file__).with_name("scoring_rules.json").read_text(encoding="utf-8"))
VERSION = RULES["version"] + "-interview-v2"


def role_key(fields):
    role = fields.get("role", "").replace(" ", "")
    direction = fields.get("direction", "").replace(" ", "").lower()
    if role == "后端开发":
        return "backend"
    if role == "前端开发":
        return "frontend"
    if role == "AI产品经理":
        return "product"
    if role == "软件测试":
        if "开发" in direction:
            return "testdev"
        if "功能" in direction:
            return "testing"
    if role == "AI应用开发":
        if "agent" in direction or "智能体" in direction:
            return "agent"
        if "大模型" in direction or "llm" in direction:
            return "llm"
    raise ValueError("请选择已支持的岗位及方向后再开始面试")


def snapshot(fields):
    key = role_key(fields)
    selected = RULES["roles"][key]
    return {"version": VERSION, "rubricVersion": RULES["version"], "interviewPolicy": INTERVIEW_POLICY,
            "roleKey": key, "approvedOn": RULES["approvedOn"],
            "dimensions": deepcopy(RULES["common"] + selected["dimensions"]),
            "applicability": selected["applicability"], "scale": RULES["scale"],
            "aggregation": "group_once_dimension_mean_weighted_coverage_v1"}


def is_abstention(text):
    # Only unmistakable empty demonstrations. A longer hypothetical solution is NOT discarded.
    value = re.sub(r"[\s，。！？、,.!?；;：:]", "", text).lower()
    for prefix in ("对不起", "抱歉", "不好意思"):
        value = value.removeprefix(prefix)
    return value in {"不会", "我不会", "不知道", "我不知道", "这个我不知道", "不清楚", "我不清楚",
                     "没做过", "我没做过", "没有做过", "我没有做过", "没有相关经历", "我没有相关经历",
                     "不了解", "我不了解", "这个没做过", "这个我没做过", "确实不会", "我确实不会"}


def dimension_ids(rubric):
    return [d["id"] for d in rubric["dimensions"]]


def validate_plan(questions, rubric):
    common = [d["id"] for d in rubric["dimensions"][:3]]
    specific = set(dimension_ids(rubric)[3:])
    covered = set()
    for question in questions:
        assigned = question.dimension_ids
        if len(assigned) != len(set(assigned)) or not set(assigned) <= specific or len(assigned) > 2:
            raise ValueError("Question uses unapproved or duplicate dimensions")
        if not question.reference_points or any(not x.strip() for x in question.reference_points):
            raise ValueError("Question reference points must be locked before display")
        covered.update(assigned)
    if covered != specific or len(common) != 3:
        raise ValueError("Main questions must explicitly cover all three role dimensions")


def validate_ratings(result, data):
    rubric = data["scoring"]
    roots = {g["id"]: g for g in data["groups"]}
    questions = {q["id"]: q for q in data["questions"]}
    answers = {a["id"]: a for a in data["answers"] if a["text"].strip() and not a["skipped"]}
    expected = {g["id"] for g in roots.values()
                if any(questions[a["question_id"]]["main"] == g["main"] for a in answers.values())}
    if len(result.ratings) != len(expected) or {g.question_id for g in result.ratings} != expected:
        raise ValueError("Ratings must cover exactly the submitted main question groups")
    common = dimension_ids(rubric)[:3]
    for group in result.ratings:
        root = roots[group.question_id]
        allowed = root["dimension_ids"]
        if not set(common) <= set(allowed):
            raise ValueError("Frozen group omits a common dimension")
        if len(group.dimensions) != len(allowed) or {d.dimension_id for d in group.dimensions} != set(allowed):
            raise ValueError("A group rating changed its preassigned dimensions")
        group_answers = [a for a in answers.values() if questions[a["question_id"]]["main"] == root["main"]]
        no_demonstration = all(is_abstention(a["text"]) for a in group_answers)
        for rating in group.dimensions:
            if rating.level is None:
                if rating.evidence:
                    raise ValueError("N/A must not claim scoring evidence")
                continue
            if no_demonstration or not rating.evidence:
                raise ValueError("Numeric levels require an observable demonstration and exact evidence")
            for evidence in rating.evidence:
                answer = answers.get(evidence.answer_id)
                if not answer or answer not in group_answers or evidence.quote not in answer["text"]:
                    raise ValueError("Rating evidence must be an exact quote within its own group")


def aggregate(rubric, groups, ratings, answered_groups):
    """Fractions keep a displayed 80% from admitting an actual 79.99% result."""
    by_group = {r["question_id"]: {d["dimension_id"]: d for d in r["dimensions"]} for r in ratings}
    dimensions, evidence_groups = [], set()
    total_coverage = Fraction(0)
    scores = {}
    for dim in rubric["dimensions"]:
        key = dim["id"]
        planned = [g for g in groups if key in g["dimension_ids"]]
        if not planned:
            raise ValueError("Invalid frozen dimension plan")
        values, items = [], []
        for group in planned:
            rating = by_group.get(group["id"], {}).get(key)
            if rating is not None:
                items.append({"questionId": group["id"], **rating})
            if rating is not None and rating["level"] is not None:
                values.append(rating["level"] * 25)
                evidence_groups.add(group["id"])
        coverage = Fraction(len(values), len(planned))
        total_coverage += coverage * Fraction(dim["weight"], 100)
        value = Fraction(sum(values), len(values)) if values else None
        if value is not None:
            scores[key] = value
        dimensions.append({"id": key, "name": dim["name"], "weight": dim["weight"],
                           "score": round(float(value), 1) if value is not None else None,
                           "coverage": round(float(coverage * 100), 1), "coveredGroups": len(values),
                           "plannedGroups": len(planned), "ratings": items})
    reasons = []
    if len(evidence_groups) < 3:
        reasons.append("至少需要3个不同题组有评分依据")
    if len(scores) != 6:
        reasons.append("六项维度均须有评分依据，当前存在N/A维度")
    if total_coverage < Fraction(4, 5):
        reasons.append("评分证据覆盖率未达到80%")
    score = None
    if not reasons:
        value = sum((scores[d["id"]] * Fraction(d["weight"], 100) for d in rubric["dimensions"]), Fraction(0))
        score = round(float(value), 1)
    return {"version": rubric["version"], "state": "ready" if score is not None else "insufficient_evidence",
            "score": score, "evidenceCoverage": round(float(total_coverage * 100), 1),
            "coverageFraction": [total_coverage.numerator, total_coverage.denominator],
            "dimensions": dimensions, "scorableGroups": len(evidence_groups),
            "answeredGroups": answered_groups, "plannedGroups": len(groups),
            "completionPercent": round(100 * answered_groups / len(groups), 1) if groups else 0,
            "reasons": reasons}


def trend_dimension(rubric):
    return rubric["dimensions"][3]["id"]
