"""Frozen interview composition and local coverage checks; no extra model requests."""
import re
import unicodedata

VERSION = "natural-jd-v2"

COMPOSITIONS = {
    3: ("experience", "jd_requirement", "scenario"),
    5: ("background", "experience", "jd_requirement", "jd_requirement", "scenario"),
    8: ("background", "experience", "jd_requirement", "jd_requirement", "scenario",
        "experience", "jd_requirement", "scenario"),
}
DESCRIPTIONS = {
    "background": "了解一段实际项目/实习的背景与本人职责，不直接考原理。",
    "experience": "围绕一段实际经历中的一个行动或选择提问，先聊怎么做。",
    "jd_requirement": "直接围绕指定JD要求聊一次实际使用或工作经历，不强行绑定简历项目。",
    "scenario": "给出贴合JD的简短假设工作场景，询问一个实际处理问题，不假定用户做过。",
}
TOOLS = re.compile(r"chatgpt|claude|cursor|copilot|gemini|通义|豆包|文心|ai\s*工具|人工智能工具", re.I)
PROJECT_BOUND = re.compile(r"(?:你的|你们的|这个|该|上述)项目|在项目[中里]|项目[中里]")
WEAK_FOCUS = {"要求", "任职要求", "岗位要求", "能力", "相关能力", "具备", "熟悉", "熟练", "掌握",
              "了解", "使用", "使用过", "经验", "项目", "工作", "优先", "加分", "负责", "相关"}


def normalized(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def natural(data):
    return data.get("interview_policy") == VERSION


def requirements(job):
    items, seen = [], set()
    for field in ("requirements", "responsibilities"):
        for line in re.split(r"[\n；;。]+", job.get(field, "")):
            line = line.strip()
            # Keep contiguous source excerpts so all existing evidence checks apply.
            for start in range(0, len(line), 400):
                quote = line[start:start + 400].strip()
                key = normalized(quote)
                if not key or key in seen:
                    continue
                seen.add(key)
                optional = bool(re.search(r"优先|加分|更佳|优选", quote))
                mandatory = bool(re.search(r"必须|必备|必需|至少|须具备", quote))
                tools = bool(TOOLS.search(quote))
                items.append({"id": f"jd{len(items) + 1}", "quote": quote, "field": field,
                              "tool_use": tools,
                              "priority": 3 if mandatory else 0 if optional else 2 if tools else 1})
    return sorted(items, key=lambda item: -item["priority"])


def blueprint(count, context):
    job, resume = context.get("job", {}), context.get("resume", {})
    targets = requirements(job)
    if not targets:
        # A short manually confirmed JD can still have a role/name/direction only.
        for field in ("direction", "name", "role"):
            quote = job.get(field, "").strip()
            if quote:
                targets = [{"id": "jd1", "quote": quote[:400], "field": field,
                            "tool_use": False, "priority": 1}]
                break
    if not targets:
        raise ValueError("An interview needs a confirmed job topic")
    has_experience = any(any(str(value).strip() for value in entry.values())
                         for field in ("projects", "internships") for entry in resume.get(field, [])
                         if isinstance(entry, dict))
    slots, used, index = [], set(), 0
    for number, category in enumerate(COMPOSITIONS[count], 1):
        if not has_experience and category in {"background", "experience"}:
            category = "jd_requirement"
        slot = {"number": number, "category": category, "instruction": DESCRIPTIONS[category]}
        if category == "jd_requirement":
            target = targets[index % len(targets)]
            index += 1
            slot["requirement_id"] = target["id"]
            slot["requirement_quote"] = target["quote"]
            if target["id"] in used:
                slot["instruction"] += "同一要求已出现过，请换一个实际侧面，避免重复问题。"
            used.add(target["id"])
        slots.append(slot)
    return {"version": VERSION, "slots": slots, "requirements": targets,
            "has_experience": has_experience}


def validate_question_text(text):
    # Punctuation cannot distinguish a related invitation from multiple topics.
    # The single-focus requirement belongs in the generation instructions;
    # question numbers and question marks must not discard a paid whole plan.
    if len(text) > 120:
        raise ValueError("Question exceeds the conversational length limit")


def validate_composition(result, plan):
    if len(result.questions) != len(plan["slots"]):
        raise ValueError("Question count does not match frozen interview slots")
    targets = {item["id"]: item for item in plan["requirements"]}
    for question, slot in zip(result.questions, plan["slots"], strict=True):
        validate_question_text(question.text)
        if question.category != slot["category"]:
            raise ValueError("Question category does not match frozen interview slot")
        if question.category in {"jd_requirement", "scenario"} and not any(b.kind == "job" for b in question.basis):
            raise ValueError("JD questions and scenarios require job evidence")
        if question.category == "jd_requirement" and PROJECT_BOUND.search(question.text):
            raise ValueError("JD requirement slots must not be bound to a resume project")
        if question.category in {"background", "experience"} and plan["has_experience"]:
            if not any(b.kind == "resume" for b in question.basis):
                raise ValueError("Experience questions require resume evidence")
        if question.category != "jd_requirement":
            if question.requirement_id or question.requirement_focus:
                raise ValueError("Only allocated JD slots may claim explicit requirement coverage")
            continue
        if question.requirement_id != slot["requirement_id"]:
            raise ValueError("Question omitted its assigned JD requirement")
        target = targets[question.requirement_id]
        focus = normalized(question.requirement_focus)
        if (len(focus) < 2 or focus in WEAK_FOCUS or focus not in normalized(target["quote"])
                or focus not in normalized(question.text)):
            raise ValueError("JD focus must occur in both the requirement and the actual question")
        if not any(b.kind == "job" and b.quote in target["quote"]
                   and focus in normalized(b.quote) for b in question.basis):
            raise ValueError("JD question must cite its allocated source requirement")
        if target["tool_use"] and not TOOLS.search(question.text):
            raise ValueError("AI tool requirements must be addressed in the actual question")
