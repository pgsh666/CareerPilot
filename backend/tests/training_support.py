"""Offline-only model/speech fixtures. Production app never loads these by default."""
import json
from threading import Event

from app.material_extract import extract_job, extract_resume
from app.training_schemas import (
    FollowDecision,
    NaturalQuestionPlan,
    PracticeFeedback,
    QuestionPlan,
    QuestionProposal,
    ReportProposal,
    ScoredFollowDecision,
    ScoredQuestionPlan,
    ScoredReportProposal,
)


class FakeGateway:
    def __init__(self, *args):
        self.calls = []
        self.fail = None
        self.block = False
        self.started = Event()
        self.release = Event()

    def generate(self, *, schema, content, validate=None, **kwargs):
        from app.model_gateway import PURPOSES
        assert kwargs.get("purpose") in PURPOSES
        data = json.loads(content)
        self.calls.append(kwargs.get("purpose"))
        if self.block:
            self.started.set()
            self.release.wait(8)
        if self.fail:
            from app.errors import ApiError
            raise ApiError(503, self.fail, "本地故障注入：生成暂不可用")
        if schema is NaturalQuestionPlan:
            specifics = data["scoring"]["dimensions"][3:]
            resume = data["context"]["resume"]
            source = next((item["name"] for item in resume.get("projects", []) if item.get("name")), "")
            targets = {item["id"]: item for item in data["interview_blueprint"]["requirements"]}
            questions = []
            for i, slot in enumerate(data["interview_blueprint"]["slots"]):
                target = targets.get(slot.get("requirement_id"))
                quote = target["quote"] if target else data["context"]["job"]["requirements"]
                focus = ""
                if target:
                    import re
                    match = re.search(r"Python|MySQL|ChatGPT|Claude|Cursor|AI工具|接口|需求|产品", quote, re.I)
                    focus = match[0] if match else quote[:12]
                text = f"能介绍一次使用{focus}的实际经历吗？" if target else (
                    "假设接口返回的结果不符合预期，你会怎么处理？" if slot["category"] == "scenario"
                    else f"说说{source}中你负责的工作可以吗？")
                questions.append({"text": f"第{i + 1}题：{text}", "topic": slot["category"],
                                  "category": slot["category"], "requirement_id": target["id"] if target else "",
                                  "requirement_focus": focus,
                                  "basis": [{"kind": "resume", "quote": source}] if slot["category"] in {"background", "experience"}
                                  else [{"kind": "job", "quote": quote}],
                                  "dimension_ids": [specifics[i % 3]["id"]],
                                  "reference_points": ["说明本题所问的实际做法与依据。"]})
            value = {"questions": questions}
        elif schema in {QuestionPlan, ScoredQuestionPlan}:
            quote = data["context"]["job"]["requirements"]
            value = {"questions": [{"text": f"第{i}题：请介绍项目背景，以及你如何实践{quote}？", "topic": "项目背景",
                                     "basis": [{"kind": "job", "quote": quote}]}
                                    for i in range(1, data["count"] + 1)]}
            if schema is ScoredQuestionPlan:
                specifics = data["scoring"]["dimensions"][3:]
                for i, q in enumerate(value["questions"]):
                    q["dimension_ids"] = [specifics[i % 3]["id"]]
                    q["reference_points"] = ["说明与本题相关的方案、个人职责或验证依据。"]
        elif schema in {FollowDecision, ScoredFollowDecision}:
            follow = "继续追问" in data["answer"]["text"]
            value = {"action": "followup" if follow else "advance", "question": "请说明你刚才提到的做法如何验证？" if follow else "",
                     "quote": data["answer"]["text"][:10] if follow else ""}
            if schema is ScoredFollowDecision:
                value["reference_points"] = ["说明刚才做法的验证步骤和判断依据。"] if follow else []
        elif schema in {ReportProposal, ScoredReportProposal}:
            qs = {q["id"]: q for q in data["questions"]}
            entries = []
            for q in data["questions"]:
                if q["follow"] != 0:
                    continue
                a = next(a for a in data["answers"] if qs[a["question_id"]]["main"] == q["main"])
                evidence = {"answer_id": a["id"], "quote": a["text"][:20], "comment": "可补充一项明确的验证依据。"}
                entries.append({"question_id": q["id"], "strengths": [evidence], "missing": [evidence]})
            first = data["answers"][0]
            value = {"summary": "这是本地状态机测试反馈，不用于专业能力验收。", "questions": entries,
                     "improvements": [{"question_id": first["question_id"], "answer_id": first["id"],
                                       "quote": first["text"][:20], "focus": "验证依据", "suggestion": "补充一项验证过程及观察结果。"}]}
            if schema is ScoredReportProposal:
                from app.scoring import is_abstention
                ratings = []
                for group in data["groups"]:
                    submitted = [a for a in data["answers"] if qs[a["question_id"]]["main"] == group["main"]]
                    if not submitted:
                        continue
                    meaningful = next((a for a in submitted if not is_abstention(a["text"])), None)
                    ratings.append({"question_id": group["id"], "dimensions": [
                        {"dimension_id": key, "level": 3 if meaningful else None,
                         "reason": "仅用于状态与计算验证的固定样例。" if meaningful else "未展示可评价内容。",
                         "evidence": [{"answer_id": meaningful["id"], "quote": meaningful["text"][:20]}] if meaningful else []}
                        for key in group["dimension_ids"]]})
                value["ratings"] = ratings
        elif schema is QuestionProposal:
            value = {"text": "假设同一接口的请求突然增多，你会怎样验证访问控制仍然正确？",
                     "topic": data["focus"], "basis": [{"kind": "question", "quote": data["question"][:20]}]}
        elif schema is PracticeFeedback:
            a = data["answers"][-1]
            value = {"strengths": [{"answer_id": a["id"], "quote": a["text"][:20], "comment": "本次回答已保存并对照原答。"}],
                     "missing": [], "comparison": "已对照本次提交与来源原答；不计算提升百分比。"}
        else:
            value = {"fields": extract_resume(data["source"]) if "Resume" in schema.__name__ else extract_job(data["source"])}
        result = schema.model_validate(value, strict=True)
        if validate:
            validate(result)
        return {"id": "offline-fixture", "output": result, "chargedUpperMicroCny": 0, "cached": False}


class FakeSpeech:
    def __init__(self):
        self.text = "这是真实提交位置的本地语音替身文本。"
        self.started = Event()
        self.release = Event()
        self.block = False

    def transcribe(self, path):
        if self.block:
            self.started.set()
            self.release.wait(8)
        return {"text": self.text, "seconds": 2, "provider": "isolated-test-fixture"}
