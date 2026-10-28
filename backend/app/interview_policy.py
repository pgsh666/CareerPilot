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
FOCUS_SEPARATORS = re.compile(r"[、，,；;/／|｜\n]+")
FOCUS_FILLER = re.compile(
    r"任职要求|岗位要求|相关能力|实际工作|实际经历|工作经验|使用经验|具有|具备|能够|"
    r"独立|完成|较强|良好|一定|实际|具体|相关|能力|经验|要求|熟悉|熟练|掌握|了解|"
    r"使用过|使用|项目|工作|优先|加分|负责|以及|如何|怎么|什么|可以|一个|一次|"
    r"ai|学习|理解|吸收|跟进|快速|领域|基础|基本|的|和|与|及|并"
)
JOB_DESCRIPTION = (
    r"(?:(?:这份|该|当前|目标|这则)\s*)?"
    r"(?:岗位\s*JD|职位\s*JD|(?<![a-z0-9])JD(?![a-z0-9])|岗位描述|职位描述|岗位说明书?|职位说明书?)"
    r"\s*(?:中|里|上)?\s*"
)
INTERVIEWER_LEAD = r"(?P<lead>^\s*|[。！？；：，!?;:,\n]\s*)"
DESCRIPTION_CONTEXT = re.compile(
    INTERVIEWER_LEAD + r"(?:根据|按照|结合|针对)\s*" + JOB_DESCRIPTION
    + r"(?:(?:的)?(?:任职|岗位)?要求)?\s*[，,：:]\s*", re.I,
)
DESCRIPTION_REQUIREMENT = re.compile(
    INTERVIEWER_LEAD + r"(?:(?:根据|按照|结合|针对)\s*)?" + JOB_DESCRIPTION
    + r"(?:(?:明确|主要|特别)?(?:提到|提出|列出|写明|提及|注明)(?:的)?\s*)?(?:的)?"
    + r"(?P<verb>(?:并不|不)?(?:要求|需要|希望|看重|强调|关注|重视|优先考虑))(?:是(?!否))?", re.I,
)


def normalized(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def interviewer_text(text):
    """Rephrase only introductory source narration; retain question substance.

    Shared by display and TTS for existing questions. Source quotations and
    submitted answers are untouched; stored question text is never updated here.
    """
    text = DESCRIPTION_CONTEXT.sub(lambda match: match["lead"] + "想请问，", text)
    return DESCRIPTION_REQUIREMENT.sub(lambda match: match["lead"] + "我们" + match["verb"], text)


def matching_focus(focus, requirement, question):
    """Find concrete shared anchors, not an entire concatenated model label.

    Keep exact short technical terms compatible. For longer labels, accept list
    members or substantive phrases of at least three characters. All candidates
    must occur in both the assigned source and the actual question; this is a
    bounded lexical check, not a claim to understand arbitrary paraphrases.
    """
    source, asked = normalized(requirement), normalized(question)
    parts = [normalized(part) for part in FOCUS_SEPARATORS.split(focus)]
    seen = set()
    for part in [normalized(focus), *parts]:
        if (len(part) >= 2 and part not in WEAK_FOCUS and len(FOCUS_FILLER.sub("", part)) >= 2 and part not in seen
                and part in source and part in asked):
            seen.add(part)
            yield part
    # Model metadata may summarize another facet of the same long requirement.
    # Recover an actual source phrase rather than rejecting a relevant question
    # merely because its private label is imprecise.
    source_parts = ([normalized(part) for part in FOCUS_SEPARATORS.split(requirement)]
                    if len(normalized(focus)) >= 5 else [])
    for part in [*parts, *source_parts]:
        if len(FOCUS_FILLER.sub("", part)) < 2:
            continue
        for size in range(min(len(part), 80), 2, -1):
            for start in range(len(part) - size + 1):
                end = start + size
                anchor = part[start:end].strip("的和与及并")
                # Never treat a fragment such as "hat" from ChatGPT as a tool.
                if ((start and part[start - 1].isascii() and part[start - 1].isalnum()
                     and part[start].isascii() and part[start].isalnum())
                        or (end < len(part) and part[end].isascii() and part[end].isalnum()
                            and part[end - 1].isascii() and part[end - 1].isalnum())):
                    continue
                if anchor in seen or len(anchor) < 3 or len(FOCUS_FILLER.sub("", anchor)) < 2 or anchor not in source:
                    continue
                seen.add(anchor)
                present = anchor in asked
                if not present and re.fullmatch(r"[\u4e00-\u9fff]{3,20}", anchor):
                    # Natural noun modifiers: 新产品 -> 新的AI产品, 需求分析 -> 需求的分析.
                    # No synonym guessing, reordered clauses or arbitrary gaps.
                    present = bool(re.search(r"(?:的|ai|人工智能){0,2}".join(anchor), asked))
                if present:
                    yield anchor


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
        matches = matching_focus(question.requirement_focus, target["quote"], question.text)
        focus, matched = None, False
        for anchor in matches:
            matched = True
            if any(b.kind == "job" and b.quote in target["quote"] and anchor in normalized(b.quote)
                   for b in question.basis):
                focus = anchor
                break
        if not matched:
            raise ValueError("JD focus must occur in both the requirement and the actual question")
        if focus is None:
            raise ValueError("JD question must cite its allocated source requirement")
        if target["tool_use"] and not TOOLS.search(question.text):
            raise ValueError("AI tool requirements must be addressed in the actual question")
        # Canonicalize private metadata only. Never rewrite the displayed question,
        # its evidence, reference points or frozen scoring dimensions.
        if normalized(question.requirement_focus) != focus:
            question.requirement_focus = focus
