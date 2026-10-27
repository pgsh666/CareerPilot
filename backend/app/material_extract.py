"""Conservative, source-only field extraction. No model calls or invented missing fields."""
import re

from app.material_schemas import JobFields, ResumeFields

RULES_VERSION = "source-rules-v1"


def labeled(source: str, labels: tuple[str, ...]) -> str:
    pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?mi)^\s*(?:{pattern})\s*[：:]\s*(.+)$", source)
    return match[1].strip()[:300] if match else ""


def section(source: str, labels: tuple[str, ...]) -> str:
    lines = source.splitlines()
    result = []
    active = False
    headings = r"(?:基本信息|教育经历|项目经历|实习经历|专业技能|技能|岗位职责|工作职责|核心职责|任职要求|岗位要求|任职资格|明确要求|其他|福利待遇)"
    for line in lines:
        clean = line.strip()
        if any(re.match(rf"^{re.escape(label)}\s*[：:]?", clean) for label in labels):
            active = True
            inline = re.sub(rf"^(?:{'|'.join(map(re.escape, labels))})\s*[：:]?\s*", "", clean)
            if inline:
                result.append(inline)
        elif active:
            if re.match(rf"^{headings}(?:\s*[：:]|\s*$)", clean):
                break
            result.append(line)
    return "\n".join(result).strip()[:20_000]


def extract_resume(source: str):
    fields = ResumeFields().model_dump()
    for field, labels in {
        "name": ("姓名", "Name"), "stage": ("求职阶段", "求职类型"),
        "school": ("学校", "院校", "毕业院校"), "major": ("专业",),
        "educationDates": ("就读时间", "教育时间"),
    }.items():
        fields[field] = labeled(source, labels)
    fields["skills"] = section(source, ("专业技能", "技能"))
    projects = []
    # Only explicit project labels split records; unlabeled text is left for correction.
    chunks = re.split(r"(?m)^\s*项目名称\s*[：:]\s*", source)[1:]
    for chunk in chunks[:40]:
        lines = chunk.splitlines()
        projects.append({
            "name": lines[0].strip()[:300] if lines else "",
            "responsibility": labeled(chunk, ("个人职责", "项目职责")),
            "content": labeled(chunk, ("项目内容", "技术方案", "项目背景")),
            "result": labeled(chunk, ("项目成果", "结果与依据", "成果与依据")),
        })
    if projects:
        fields["projects"] = projects
    internships = []
    for chunk in re.split(r"(?m)^\s*公司名称\s*[：:]\s*", source)[1:41]:
        lines = chunk.splitlines()
        internships.append({
            "company": lines[0].strip()[:300] if lines else "",
            "position": labeled(chunk, ("实习岗位",)), "dates": labeled(chunk, ("实习时间",)),
            "responsibility": labeled(chunk, ("实习职责", "工作内容与个人职责")),
            "result": labeled(chunk, ("实习成果", "成果与依据")),
        })
    if internships:
        fields["internships"] = internships
    return ResumeFields.model_validate(fields).model_dump()


def extract_job(source: str):
    fields = JobFields().model_dump()
    fields["name"] = labeled(source, ("岗位名称", "职位名称", "招聘岗位"))
    fields["company"] = labeled(source, ("公司名称", "招聘公司"))
    fields["direction"] = labeled(source, ("岗位方向", "职位方向"))
    explicit_role = labeled(source, ("岗位类别",))
    for role in ("后端开发", "前端开发", "软件测试", "AI 产品经理", "AI 应用开发"):
        if explicit_role == role or role.replace(" ", "") in fields["name"].replace(" ", ""):
            fields["role"] = role
            break
    fields["responsibilities"] = section(source, ("岗位职责", "工作职责", "核心职责"))
    fields["requirements"] = section(source, ("任职要求", "岗位要求", "任职资格", "明确要求"))
    return JobFields.model_validate(fields).model_dump()


def extraction_evidence(source: str, fields: dict):
    return {key: {"text": value, "start": source.find(value), "end": source.find(value) + len(value)}
            for key, value in fields.items()
            if isinstance(value, str) and value and value in source}


def job_title(current, previous_fields, fields):
    """Keep custom list names while automatic names follow the corrected job name."""
    previous_name = (previous_fields or {}).get("name") or ""
    if not current or current == "新增岗位 JD" or current == previous_name[:180]:
        return (fields.get("name") or current or "新增岗位 JD")[:180]
    return current
