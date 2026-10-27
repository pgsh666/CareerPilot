from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EmailInput(InputModel):
    email: EmailStr

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return str(value).strip().lower()


class CloseAccountInput(EmailInput):
    confirmed: Literal[True]


class ChallengeInput(EmailInput):
    purpose: Literal["register", "password_reset"]


class EmailCodeInput(EmailInput):
    code: str = Field(min_length=6, max_length=8, pattern=r"^\d+$")


class RegisterInput(EmailCodeInput):
    password: SecretStr = Field(min_length=8, max_length=128)
    confirmation: SecretStr = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def matching_passwords(self):
        if self.password.get_secret_value() != self.confirmation.get_secret_value():
            raise ValueError("Passwords do not match")
        return self


class LoginInput(EmailInput):
    password: SecretStr = Field(min_length=1, max_length=128)


class ChangePasswordInput(InputModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=8, max_length=128)
    confirmation: SecretStr = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def matching_new_password(self):
        password = self.password.get_secret_value()
        if password != self.confirmation.get_secret_value():
            raise ValueError("Passwords do not match")
        if password == self.current_password.get_secret_value():
            raise ValueError("New password must be different")
        return self


Avatar = Literal["default", "pilot", "star", "mountain", "cloud", "leaf"]


class ProfileInput(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=24)
    avatar: Avatar | None = None

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.avatar is None:
            raise ValueError("No changes supplied")
        return self
