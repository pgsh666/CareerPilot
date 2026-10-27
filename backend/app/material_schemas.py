from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

TextField = Annotated[str, StringConstraints(max_length=20_000)]
ShortField = Annotated[str, StringConstraints(max_length=300)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ProjectFields(Input):
    name: ShortField = ""
    responsibility: TextField = ""
    content: TextField = ""
    result: TextField = ""


class InternshipFields(Input):
    company: ShortField = ""
    position: ShortField = ""
    dates: ShortField = ""
    responsibility: TextField = ""
    result: TextField = ""


class EducationFields(Input):
    school: ShortField = ""
    major: ShortField = ""
    dates: ShortField = ""


class ResumeFields(Input):
    name: ShortField = ""
    stage: ShortField = ""
    school: ShortField = ""
    major: ShortField = ""
    educationDates: ShortField = ""
    skills: TextField = ""
    educations: list[EducationFields] = Field(default_factory=list, max_length=20)
    projects: list[ProjectFields] = Field(default_factory=lambda: [ProjectFields()], max_length=40)
    internships: list[InternshipFields] = Field(default_factory=lambda: [InternshipFields()], max_length=40)


class ResumeSave(Input):
    revision: int = Field(ge=1)
    fields: ResumeFields

    @model_validator(mode="after")
    def nonblank(self):
        data = self.fields.model_dump()
        values = [v for v in data.values() if isinstance(v, str)]
        values += [v for k in ("projects", "internships", "educations") for item in data[k] for v in item.values()]
        if not any(value.strip() for value in values):
            raise ValueError("At least one material field must be nonblank")
        return self


class Rename(Input):
    revision: int = Field(ge=1)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]


class Revision(Input):
    revision: int = Field(ge=1)


class JobFields(Input):
    name: ShortField = ""
    company: ShortField = ""
    role: Literal["", "后端开发", "前端开发", "软件测试", "AI 产品经理", "AI 应用开发"] = ""
    direction: ShortField = ""
    responsibilities: TextField = ""
    requirements: TextField = ""
    inference: TextField = ""
    useInference: bool = False


class JobParse(Input):
    source: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    revision: int | None = Field(default=None, ge=1)

    @field_validator("source", mode="before")
    @classmethod
    def normalize_newlines(cls, value):
        return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else value


class JobSave(Input):
    revision: int = Field(ge=1)
    source: str = Field(max_length=20_000)
    fields: JobFields

    @field_validator("source", mode="before")
    @classmethod
    def normalize_newlines(cls, value):
        return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else value

    @model_validator(mode="after")
    def required_fields(self):
        if not all(getattr(self.fields, k).strip() for k in ("name", "role", "direction", "requirements")):
            raise ValueError("Job name, role, direction and requirements must be confirmed")
        return self
