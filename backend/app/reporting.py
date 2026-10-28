"""Group report turns explicitly and normalize IDs without inventing scores."""
from copy import deepcopy
from types import SimpleNamespace

from pydantic import Field, model_validator

from app.scoring import validate_ratings
from app.training_schemas import GroupRating, QuestionFeedback, ScoredReportProposal


def expected_roots(data):
    questions = {q["id"]: q for q in data["questions"]}
    answered = {questions[a["question_id"]]["main"] for a in data["answers"]
                if a["text"] and not a["skipped"]}
    return [q for q in data["questions"] if q["follow"] == 0 and q["main"] in answered]


def evidence_spans(data):
    refs, by_answer = {}, {}
    for answer in data["answers"]:
        if not answer["text"] or answer["skipped"]:
            continue
        spans = []
        for start in range(0, len(answer["text"]), 40):
            quote = answer["text"][start:start + 40]
            key = f"e{len(refs) + 1}"
            refs[key] = {"answer_id": answer["id"], "question_id": answer["question_id"], "quote": quote}
            spans.append({"id": key, "text": quote})
        by_answer[answer["id"]] = spans
    return refs, by_answer


def grouped_input(data):
    groups = []
    frozen = {g["id"]: g for g in data["groups"]}
    _, by_answer = evidence_spans(data)
    for root in expected_roots(data):
        turns = []
        for question in data["questions"]:
            if question["main"] != root["main"]:
                continue
            answers = [{"answer_id": a["id"], "evidence_spans": by_answer[a["id"]]} for a in data["answers"]
                       if a["question_id"] == question["id"] and a["text"] and not a["skipped"]]
            turns.append({"turn_id": question["id"], "follow": question["follow"],
                          "question": question.get("text", ""),
                          "reference_points": question.get("reference_points", []), "answers": answers})
        groups.append({"question_id": root["id"], "main": root["main"],
                       "dimension_ids": frozen[root["id"]]["dimension_ids"], "turns": turns})
    return {"context": data.get("context", {}), "scoring": data["scoring"],
            "interview_policy": data.get("interview_policy"),
            "expected_group_ids": [g["question_id"] for g in groups], "report_groups": groups}


def output_schema(data):
    ids = [root["id"] for root in expected_roots(data)]
    refs, _ = evidence_spans(data)
    answers = {a["id"]: a for a in data["answers"] if a["text"] and not a["skipped"]}
    questions = {q["id"]: q for q in data["questions"]}

    class GroupedInterviewReport(ScoredReportProposal):
        # Compatibility parsing may receive one row per turn (at most 8*3).
        # Business validation below still permits only one rating per main group.
        ratings: list[GroupRating] = Field(max_length=24)

        @model_validator(mode="before")
        @classmethod
        def bind_source_references(cls, value):
            if not isinstance(value, dict):
                return value
            value = deepcopy(value)

            def items(container, field):
                result = container.get(field)
                return result if isinstance(result, list) else []

            def resolve(item, *, improvement=False):
                if not isinstance(item, dict):
                    return
                if "evidence_ref" in item:
                    reference = item.pop("evidence_ref")
                    if not isinstance(reference, str) or reference not in refs:
                        raise ValueError("Unknown report evidence reference")
                    source = refs[reference]
                    fields = ("answer_id", "quote", "question_id") if improvement else ("answer_id", "quote")
                    for field in fields:
                        if field in item and item[field] != source[field]:
                            claimed = questions.get(item[field]) if field == "question_id" and isinstance(item[field], str) else None
                            actual = questions.get(source["question_id"])
                            if not claimed or claimed["main"] != actual["main"]:
                                raise ValueError("Report evidence reference conflicts with explicit fields")
                        item[field] = source[field]
                elif improvement and "question_id" not in item and item.get("answer_id") in answers:
                    item["question_id"] = answers[item["answer_id"]]["question_id"]

            for group in items(value, "questions"):
                if isinstance(group, dict):
                    for field in ("strengths", "missing"):
                        for item in items(group, field):
                            resolve(item)
            for group in items(value, "ratings"):
                if isinstance(group, dict):
                    for dimension in items(group, "dimensions"):
                        if isinstance(dimension, dict):
                            for item in items(dimension, "evidence"):
                                resolve(item)
            for item in items(value, "improvements"):
                resolve(item, improvement=True)
            return value

        @classmethod
        def model_json_schema(cls, *args, **kwargs):
            value = super().model_json_schema(*args, **kwargs)
            for field in ("questions", "ratings"):
                value["properties"][field].update(minItems=len(ids), maxItems=len(ids))
            for name in ("QuestionFeedback", "GroupRating"):
                value["$defs"][name]["properties"]["question_id"].update(enum=ids)
            value["properties"]["summary"]["maxLength"] = 180
            for field in ("strengths", "missing"):
                value["$defs"]["QuestionFeedback"]["properties"][field]["maxItems"] = 1
            value["$defs"]["DimensionRating"]["properties"]["reason"]["maxLength"] = 40
            value["$defs"]["DimensionRating"]["properties"]["evidence"]["maxItems"] = 1
            value["$defs"]["Evidence"]["properties"]["comment"]["maxLength"] = 80
            value["$defs"]["Improvement"]["properties"]["suggestion"]["maxLength"] = 100
            for name in ("Evidence", "RatingEvidence", "Improvement"):
                definition = value["$defs"][name]
                removed = {"answer_id", "quote", "question_id"} if name == "Improvement" else {"answer_id", "quote"}
                for field in removed:
                    definition["properties"].pop(field, None)
                definition["properties"]["evidence_ref"] = {"type": "string", "enum": list(refs),
                    "description": "Choose an existing evidence_spans.id from the same main question group."}
                definition["required"] = [field for field in definition["required"] if field not in removed] + ["evidence_ref"]
            return value

    return GroupedInterviewReport


def normalize_report(result, data):
    """Validate every original row before coalescing harmless turn/group IDs.

    Conflicting ratings are never discarded, averaged or changed into N/A.
    Work on a copy so rejected caches retain the original provider output.
    """
    candidate = result.model_copy(deep=True)
    questions = {q["id"]: q for q in data["questions"]}
    roots = {q["main"]: q["id"] for q in expected_roots(data)}
    frozen = {g["id"]: g for g in data["groups"]}
    answers = {a["id"]: a for a in data["answers"] if a["text"] and not a["skipped"]}

    def root_for(key):
        question = questions.get(key)
        if not question or question["main"] not in roots:
            raise ValueError("Report omits or invents answered questions")
        return roots[question["main"]]

    def evidence_in_group(evidence, key):
        answer = answers.get(evidence.answer_id)
        if not answer or root_for(answer["question_id"]) != root_for(key):
            raise ValueError("Evidence crosses main question groups")
        if evidence.quote not in answer["text"]:
            raise ValueError("Evidence does not match the actual answer")

    feedback = {}
    for item in candidate.questions:
        root = root_for(item.question_id)
        target = feedback.setdefault(root, {"strengths": [], "missing": []})
        for field in ("strengths", "missing"):
            for evidence in getattr(item, field):
                evidence_in_group(evidence, item.question_id)
                if evidence not in target[field]:
                    target[field].append(evidence)
    for item in candidate.improvements:
        # answer_id identifies the exact turn. A model-supplied group/root ID is
        # harmless only when the quote is authentic and both belong to one group.
        evidence_in_group(item, item.question_id)
        item.question_id = answers[item.answer_id]["question_id"]

    ratings = {}
    for item in candidate.ratings:
        root = root_for(item.question_id)
        item.question_id = root
        validate_ratings(SimpleNamespace(ratings=[item]), {**data, "groups": [frozen[root]]})
        previous = ratings.get(root)
        if previous:
            first = sorted((d.model_dump() for d in previous.dimensions), key=lambda d: d["dimension_id"])
            second = sorted((d.model_dump() for d in item.dimensions), key=lambda d: d["dimension_id"])
            if first != second:
                raise ValueError("Conflicting ratings within one main question group")
        else:
            ratings[root] = item
    candidate.questions = [QuestionFeedback(question_id=key, strengths=value["strengths"][:4],
                                            missing=value["missing"][:4]) for key, value in feedback.items()]
    candidate.ratings = list(ratings.values())
    return candidate
