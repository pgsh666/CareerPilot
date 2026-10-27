from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)


class StartInterview(Input):
    resume_id: str = Field(min_length=1, max_length=64)
    job_id: str = Field(min_length=1, max_length=64)
    count: Literal[3, 5, 8] = 5
    confirmed: Literal[True]
    replace_id: str | None = Field(default=None, max_length=64)


class StartPractice(Input):
    task_id: str = Field(min_length=1, max_length=64)
    replace_id: str | None = Field(default=None, max_length=64)


class ResumeTraining(Input):
    replace_id: str | None = Field(default=None, max_length=64)


class DraftInput(Input):
    question_id: str
    revision: int = Field(ge=1)
    text: str = Field(max_length=20_000)


class AnswerInput(Input):
    question_id: str
    method: Literal["voice", "keyboard", "skip"]
    text: str | None = Field(default=None, max_length=20_000)
    transcript_id: str | None = None
    fault_id: str | None = None
    confirmed: bool = False


class Confirm(Input):
    confirmed: Literal[True]


class ActivityInput(Input):
    lease: str = Field(pattern=r"^[a-f0-9-]{36}$")
    sequence: int = Field(ge=1, le=9_000_000_000)
    elapsed_ms: int = Field(ge=0, le=8000)
    active: bool


class LeaseInput(Input):
    lease: str = Field(pattern=r"^[a-f0-9-]{36}$")
    takeover: bool = False
    release: bool = False


class FaultInput(Input):
    question_id: str
    reason: Literal["permission_denied", "device_unavailable", "browser_unsupported",
                    "recording_failed", "transcription_failed", "transcription_timeout", "no_speech"]


class Basis(Input):
    kind: Literal["resume", "job", "answer", "question"]
    quote: str = Field(min_length=1, max_length=500)


class QuestionProposal(Input):
    text: str = Field(min_length=5, max_length=1500)
    topic: str = Field(min_length=1, max_length=80)
    basis: list[Basis] = Field(min_length=1, max_length=4)


class QuestionPlan(Input):
    questions: list[QuestionProposal] = Field(min_length=3, max_length=8)


class ScoredQuestionProposal(QuestionProposal):
    dimension_ids: list[str] = Field(max_length=2)
    reference_points: list[str] = Field(min_length=1, max_length=5)


class ScoredQuestionPlan(Input):
    questions: list[ScoredQuestionProposal] = Field(min_length=3, max_length=8)


class NaturalQuestionProposal(ScoredQuestionProposal):
    text: str = Field(min_length=5, max_length=120)
    category: Literal["background", "experience", "jd_requirement", "scenario"]
    requirement_id: str = Field(default="", max_length=20)
    requirement_focus: str = Field(default="", max_length=80)
    reference_points: list[str] = Field(min_length=1, max_length=3)

    @field_validator("requirement_id", "requirement_focus", mode="before")
    @classmethod
    def empty_optional_metadata(cls, value):
        return "" if value is None else value

    @field_validator("dimension_ids", mode="before")
    @classmethod
    def remove_implicit_common_dimensions(cls, value):
        if isinstance(value, list):
            return [key for key in value if key not in ("relevance", "logic", "evidence")]
        return value


class NaturalQuestionPlan(Input):
    questions: list[NaturalQuestionProposal] = Field(min_length=3, max_length=8)


class FollowDecision(Input):
    action: Literal["followup", "advance"]
    question: str = Field(max_length=1500)
    quote: str = Field(max_length=500)


class ScoredFollowDecision(FollowDecision):
    reference_points: list[str] = Field(max_length=5)


class Evidence(Input):
    answer_id: str
    quote: str = Field(min_length=1, max_length=1500)
    comment: str = Field(min_length=1, max_length=1500)


class QuestionFeedback(Input):
    question_id: str
    strengths: list[Evidence] = Field(max_length=4)
    missing: list[Evidence] = Field(max_length=4)


class Improvement(Input):
    question_id: str
    answer_id: str
    quote: str = Field(min_length=1, max_length=1500)
    focus: str = Field(min_length=1, max_length=80)
    suggestion: str = Field(min_length=1, max_length=1500)


class ReportProposal(Input):
    summary: str = Field(min_length=1, max_length=2000)
    questions: list[QuestionFeedback] = Field(max_length=24)
    improvements: list[Improvement] = Field(max_length=3)


class RatingEvidence(Input):
    answer_id: str
    quote: str = Field(min_length=1, max_length=500)


class DimensionRating(Input):
    dimension_id: str
    level: int | None = Field(ge=0, le=4)
    reason: str = Field(min_length=1, max_length=500)
    evidence: list[RatingEvidence] = Field(max_length=2)


class GroupRating(Input):
    question_id: str
    dimensions: list[DimensionRating] = Field(min_length=3, max_length=5)


class ScoredReportProposal(ReportProposal):
    ratings: list[GroupRating] = Field(max_length=8)


class PracticeFeedback(Input):
    strengths: list[Evidence] = Field(max_length=4)
    missing: list[Evidence] = Field(max_length=4)
    comparison: str = Field(max_length=1500)
