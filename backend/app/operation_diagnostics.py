"""Admin-safe diagnostic views, never model prompts, outputs or exception text."""
import json
import re

from sqlalchemy import select

from app.model_validation import safe_diagnostic
from app.models import GenerationJob, ModelSpend

STAGE_LABELS = {"envelope": "响应完整性", "json": "JSON格式", "schema": "字段与结构校验",
                "contract": "内容规则校验", "transport": "模型连接与响应", "worker": "后台任务处理",
                "recovery": "已付费结果离线复核"}
REASONS = {
    "SCHEMA_INVALID": "返回内容缺少必要字段，或字段类型、范围不符合约定。",
    "JSON_INVALID": "返回内容无法解析为完整JSON对象。",
    "INCOMPLETE_RESPONSE": "供应商未完整返回内容，可能被输出长度等限制中断。",
    "COMPOUND_QUESTION": "旧版规则按问号数量或题号判断多个问题；该格式拦截现已修正。",
    "QUESTION_TOO_LONG": "题干超过当前自然对话长度上限。",
    "QUESTION_COUNT_OR_DUPLICATES": "题目数量与预设不一致，或存在重复题目。",
    "QUESTION_COUNT_MISMATCH": "题目数量与锁定题位不一致。",
    "QUESTION_CATEGORY_MISMATCH": "题型与锁定的经历、JD或情境题位不一致。",
    "SOURCE_EVIDENCE_MISMATCH": "引用文字无法在确认的材料中找到。",
    "JD_EVIDENCE_MISSING": "JD题或岗位情境题缺少JD原文依据。",
    "JD_BOUND_TO_PROJECT": "JD实践题被强行限定到简历项目。",
    "RESUME_EVIDENCE_MISSING": "经历题缺少对应简历原文依据。",
    "UNEXPECTED_JD_METADATA": "非JD题位填入了不适用的JD考察项。",
    "JD_REQUIREMENT_MISMATCH": "没有考察题位预先分配的JD要求。",
    "JD_FOCUS_MISMATCH": "实质考察词没有同时体现在分配要求和实际题干中。",
    "JD_SOURCE_MISMATCH": "引用不属于分配的JD要求，或未包含本题考察词。",
    "AI_TOOL_REQUIREMENT_OMITTED": "AI工具要求没有在实际题干中体现。",
    "SCORING_DIMENSIONS_INVALID": "包含未批准或重复的评分专项。",
    "SCORING_COVERAGE_MISSING": "整场题目未覆盖已确认的三个岗位专项。",
    "REFERENCE_POINTS_MISSING": "题目缺少展示前必须锁定的参考要点。",
    "FOLLOWUP_EVIDENCE_OR_LIMIT": "追问缺少真实回答依据，或超过允许次数。",
    "ANSWER_EVIDENCE_MISMATCH": "评价引文无法与同题组的实际回答核对。",
    "CACHED_OUTPUT_ACCEPTED": "按原快照离线复核已付费结果并采纳，未新增模型请求。原调用失败记录仍保留。",
    "GENERATION_FAILED": "后台处理未完成，未保存更细的异常诊断。",
    "CONTRACT_REJECTED": "返回内容未通过业务规则检查；可用签名定位后端对应校验。",
    "MODEL_COST_UNCERTAIN": "请求已发出但费用或完成状态不明，保留预留额度且不自动重试。",
    "TIMEOUT": "模型请求超过处理时限，费用和完成状态需要核实。",
    "HTTP_ERROR": "模型服务响应异常，费用和完成状态需要核实。",
    "UNEXPECTED_FOLLOWUP": "结束题组的结果中仍包含追问题目。",
    "FOLLOWUP_REFERENCE_POINTS_INVALID": "追问补充要点缺失，或结束题组时仍附加追问要点。",
    "VARIANT_REPEATS_ORIGINAL": "变式题重复了原题。",
    "REPORT_GROUPS_MISMATCH": "报告遗漏已回答题组，或增加了未回答题组。",
    "CROSS_GROUP_EVIDENCE": "反馈引用了其他主问题题组的回答。",
    "RATING_GROUPS_MISMATCH": "评分题组与实际提交的题组不一致。",
    "COMMON_DIMENSION_MISSING": "锁定评分计划缺少必需的通用维度。",
    "RATING_DIMENSIONS_MISMATCH": "评分更改了本题组预先锁定的维度。",
    "NA_EVIDENCE_CONFLICT": "无可评分依据的维度仍附带数值评分证据。",
    "RATING_EVIDENCE_MISSING": "数值评分缺少可评价内容或真实回答引文。",
    "RATING_QUOTE_MISMATCH": "评分引文与同组真实回答无法逐字核对。",
    "FROZEN_PLAN_INVALID": "锁定的评分维度计划不完整或重复。",
    "UNCONFIRMED_INFERENCE": "材料整理擅自启用了尚未由用户确认的推断。",
    "EXTRACTION_SOURCE_MISMATCH": "材料整理中出现无法在原文核对的内容。",
}
ISSUES = {"missing": "缺少必填字段", "extra_forbidden": "包含未允许字段", "literal_error": "枚举值不符合约定",
          "string_type": "应为文字", "string_too_short": "文字过短", "string_too_long": "文字过长",
          "list_type": "应为列表", "dict_type": "应为对象", "int_type": "应为整数", "too_short": "项目数量不足",
          "too_long": "项目数量超限", "greater_than_equal": "低于允许下限", "less_than_equal": "超过允许上限"}


def diagnostic_view(value, *, error_code=None):
    raw = safe_diagnostic(value)
    if raw is None:
        return {"availability": "not_recorded" if error_code else "none", "raw": None,
                "reason": "该记录未保存具体诊断项，不能据此确定是哪条校验失败。" if error_code else "未记录校验失败。",
                "stageLabel": None, "rule": None, "issues": []}
    return {"availability": "recorded", "raw": raw,
            "stageLabel": STAGE_LABELS[raw["stage"]], "rule": raw["rule"],
            "reason": REASONS.get(raw["rule"], "后端规则检查未通过。"),
            "issues": [{"path": format_path(item["path"]), "type": item["type"],
                        "reason": ISSUES.get(item["type"], "字段值不符合结构约定")}
                       for item in raw.get("issues", [])]}


def format_path(parts):
    value = ""
    for part in parts:
        value += f"[{part}]" if isinstance(part, int) else ("." if value else "") + part
    return value or "根对象"


def backfill_log_diagnostics(db, lines):
    pattern = re.compile(r"model_output_rejected request_key=([A-Za-z0-9_-]{16,80}) diagnostic=(\{.*\})$")
    counts = {"matched": 0, "callsUpdated": 0, "tasksUpdated": 0}
    for line in lines:
        match = pattern.search(line.strip())
        if not match:
            continue
        try:
            detail = safe_diagnostic(json.loads(match[2]))
        except (ValueError, TypeError):
            continue
        if detail is None:
            continue
        spend = db.scalar(select(ModelSpend).where(ModelSpend.request_key == match[1]))
        if not spend or spend.error_code != "MODEL_OUTPUT_INVALID":
            continue
        counts["matched"] += 1
        if not spend.diagnostic:
            spend.diagnostic = detail
            counts["callsUpdated"] += 1
        if "-attempt-" in match[1]:
            job_id, attempt = match[1].rsplit("-attempt-", 1)
            job = db.get(GenerationJob, job_id)
            if (job and attempt.isdigit() and job.attempts == int(attempt)
                    and job.state == "failed" and job.error_code == "MODEL_OUTPUT_INVALID" and not job.diagnostic):
                job.diagnostic = detail
                counts["tasksUpdated"] += 1
    return counts
