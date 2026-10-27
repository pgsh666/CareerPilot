"""Content-free output diagnostics. Never include model text or validation inputs."""
import hashlib
import re

from pydantic import ValidationError

FIELDS = frozenset({
    "questions", "text", "topic", "basis", "kind", "quote", "dimension_ids", "reference_points",
    "category", "requirement_id", "requirement_focus", "action", "question", "summary", "strengths",
    "missing", "improvements", "ratings", "dimensions", "dimension_id", "level", "reason", "evidence",
    "question_id", "answer_id", "comment", "focus", "suggestion", "comparison", "fields", "name",
    "school", "major", "stage", "educationDates", "educations", "skills", "projects", "internships",
    "responsibility", "content", "result", "company", "position", "dates", "role", "direction",
    "responsibilities", "requirements", "inference", "useInference",
})
RULES = {
    "Wrong question count or duplicates": "QUESTION_COUNT_OR_DUPLICATES",
    "Question material evidence is not authentic": "SOURCE_EVIDENCE_MISMATCH",
    "Ask one concise conversational question at a time": "COMPOUND_QUESTION",
    "Question exceeds the conversational length limit": "QUESTION_TOO_LONG",
    "Question count does not match frozen interview slots": "QUESTION_COUNT_MISMATCH",
    "Question category does not match frozen interview slot": "QUESTION_CATEGORY_MISMATCH",
    "JD questions and scenarios require job evidence": "JD_EVIDENCE_MISSING",
    "JD requirement slots must not be bound to a resume project": "JD_BOUND_TO_PROJECT",
    "Experience questions require resume evidence": "RESUME_EVIDENCE_MISSING",
    "Only allocated JD slots may claim explicit requirement coverage": "UNEXPECTED_JD_METADATA",
    "Question omitted its assigned JD requirement": "JD_REQUIREMENT_MISMATCH",
    "JD focus must occur in both the requirement and the actual question": "JD_FOCUS_MISMATCH",
    "JD question must cite its allocated source requirement": "JD_SOURCE_MISMATCH",
    "AI tool requirements must be addressed in the actual question": "AI_TOOL_REQUIREMENT_OMITTED",
    "Question uses unapproved or duplicate dimensions": "SCORING_DIMENSIONS_INVALID",
    "Question reference points must be locked before display": "REFERENCE_POINTS_MISSING",
    "Main questions must explicitly cover all three role dimensions": "SCORING_COVERAGE_MISSING",
    "Invalid follow-up": "FOLLOWUP_EVIDENCE_OR_LIMIT",
    "Evidence does not match the actual answer": "ANSWER_EVIDENCE_MISMATCH",
    "Incomplete generation": "INCOMPLETE_RESPONSE",
    "An advance must not add a question": "UNEXPECTED_FOLLOWUP",
    "Follow-up reference points must be locked, or empty when advancing": "FOLLOWUP_REFERENCE_POINTS_INVALID",
    "Variant repeats original": "VARIANT_REPEATS_ORIGINAL",
    "Report omits or invents answered questions": "REPORT_GROUPS_MISMATCH",
    "Evidence crosses main question groups": "CROSS_GROUP_EVIDENCE",
    "Ratings must cover exactly the submitted main question groups": "RATING_GROUPS_MISMATCH",
    "Frozen group omits a common dimension": "COMMON_DIMENSION_MISSING",
    "A group rating changed its preassigned dimensions": "RATING_DIMENSIONS_MISMATCH",
    "N/A must not claim scoring evidence": "NA_EVIDENCE_CONFLICT",
    "Numeric levels require an observable demonstration and exact evidence": "RATING_EVIDENCE_MISSING",
    "Rating evidence must be an exact quote within its own group": "RATING_QUOTE_MISMATCH",
    "Invalid frozen dimension plan": "FROZEN_PLAN_INVALID",
    "Unconfirmed inference cannot be enabled by the model": "UNCONFIRMED_INFERENCE",
    "Extraction contains unsupported material": "EXTRACTION_SOURCE_MISMATCH",
}

STAGES = frozenset({"envelope", "json", "schema", "contract", "transport", "worker", "recovery"})
KNOWN_RULES = frozenset(RULES.values()) | {
    "SCHEMA_INVALID", "JSON_INVALID", "CONTRACT_REJECTED", "GENERATION_FAILED",
    "CACHED_OUTPUT_ACCEPTED", "MODEL_COST_UNCERTAIN", "TIMEOUT", "HTTP_ERROR",
}
SCHEMA_TYPES = frozenset({
    "missing", "extra_forbidden", "string_type", "string_too_short", "string_too_long",
    "list_type", "dict_type", "model_type", "model_attributes_type", "literal_error",
    "too_short", "too_long", "int_type", "int_parsing", "float_type", "bool_type", "bool_parsing",
    "greater_than", "greater_than_equal", "less_than", "less_than_equal", "value_error",
    "finite_number", "json_invalid", "none_required", "enum", "string_pattern_mismatch",
})


def safe_diagnostic(value):
    """Allowlist every exposed field, including data read back from old caches/logs."""
    if (not isinstance(value, dict) or not isinstance(value.get("stage"), str)
            or not isinstance(value.get("rule"), str)
            or value["stage"] not in STAGES or value["rule"] not in KNOWN_RULES):
        return None
    result = {"stage": value["stage"], "rule": value["rule"]}
    signature = value.get("signature")
    if isinstance(signature, str) and re.fullmatch(r"[a-f0-9]{12,64}", signature):
        result["signature"] = signature
    if isinstance(value.get("issues"), list):
        issues = []
        for issue in value["issues"][:5]:
            if not isinstance(issue, dict):
                continue
            path = issue.get("path", [])
            if not isinstance(path, list):
                path = []
            path = [part if (type(part) is int and 0 <= part <= 10000) or (isinstance(part, str) and part in FIELDS)
                    else "_" for part in path[:12]]
            issue_type = issue.get("type")
            issues.append({"path": path, "type": issue_type if isinstance(issue_type, str) and issue_type in SCHEMA_TYPES else "validation_error"})
        result["issues"] = issues
    if value["stage"] == "recovery" and isinstance(value.get("sourceSpendId"), str):
        if re.fullmatch(r"[a-f0-9-]{36}", value["sourceSpendId"]):
            result["sourceSpendId"] = value["sourceSpendId"]
    return result


def diagnostic(error, stage):
    if isinstance(error, ValidationError):
        issues = []
        for item in error.errors(include_url=False, include_input=False, include_context=False)[:5]:
            path = [part if isinstance(part, int) or part in FIELDS else "_" for part in item["loc"]]
            issues.append({"path": path, "type": item["type"]})
        return {"stage": "schema", "rule": "SCHEMA_INVALID", "issues": issues}
    if stage == "json":
        return {"stage": stage, "rule": "JSON_INVALID"}
    return {"stage": stage, "rule": RULES.get(str(error), "CONTRACT_REJECTED"),
            "signature": hashlib.sha256(str(error).encode()).hexdigest()[:12]}


def public_message(detail):
    if detail.get("rule") == "INCOMPLETE_RESPONSE":
        reason = "模型未完整返回生成内容"
    elif detail.get("stage") == "schema":
        reason = "模型返回内容的结构或必要字段不符合要求"
    elif detail.get("stage") in {"json", "envelope"}:
        reason = "模型返回内容的格式不完整"
    elif detail.get("rule", "").startswith("SCORING_"):
        reason = "生成题目的考察维度不符合已确认规则"
    elif detail.get("rule", "").startswith(("JD_", "AI_TOOL_")):
        reason = "生成题目未通过JD要求覆盖检查"
    elif "EVIDENCE" in detail.get("rule", "") or "SOURCE" in detail.get("rule", ""):
        reason = "生成内容的引用依据未能与材料或回答核对"
    else:
        reason = "模型输出未通过内容检查"
    return reason + "；已记录费用，未自动重试"


REJECTED_FORMAT = "careerpilot-rejected-output-v1"


def rejected_result(output, detail):
    # Keep only schema-validated structured results in the existing owner-private
    # cache. A failed result never becomes an accepted model answer by itself.
    if output is None or detail.get("stage") != "contract":
        return None
    return {"format": REJECTED_FORMAT, "output": output.model_dump(mode="json"),
            "diagnostic": detail}


def rejected_output(value):
    if isinstance(value, dict) and value.get("format") == REJECTED_FORMAT and isinstance(value.get("output"), dict):
        return value["output"]
    return None
