from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAREERPILOT_", env_file=BACKEND_DIR / ".env", extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["development", "production", "test"] = "development"
    database_url: SecretStr | None = None
    secret_key: SecretStr | None = None
    allowed_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    cookie_name: str = "careerpilot_session"
    cookie_secure: bool = False
    session_days: int = Field(default=7, ge=1, le=90)
    code_digits: int = Field(default=6, ge=6, le=8)
    code_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    code_resend_seconds: int = Field(default=60, ge=10, le=3600)
    code_max_attempts: int = Field(default=5, ge=1, le=20)
    login_limit: int = Field(default=10, ge=1, le=100)
    login_window_seconds: int = Field(default=300, ge=30, le=3600)
    smtp_host: str = "127.0.0.1"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_starttls: bool = False
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    mail_from: str = "CareerPilot <noreply@careerpilot.local>"
    material_directory: Path = BACKEND_DIR / "data" / "materials"
    material_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    material_text_limit: int = Field(default=200_000, ge=1000, le=500_000)
    material_extract_timeout: int = Field(default=20, ge=1, le=60)
    jd_text_limit: int = Field(default=20_000, ge=1000, le=20_000)
    # Reserved for model integration; this field alone never enables model calls.
    deepseek_api_key: SecretStr | None = None
    # Test allowance is cumulative for this project, separate from the monthly product budget.
    model_usage_mode: Literal["test", "application"] = "test"
    model_test_budget_cny: Decimal = Field(default=Decimal("20"), ge=0, le=20)
    model_test_max_calls: int = Field(default=2, ge=0, le=2)
    model_monthly_budget_cny: Decimal = Field(default=Decimal("50"), ge=0, le=50)
    deepseek_model: Literal["deepseek-flash"] = "deepseek-flash"
    model_timeout_seconds: int = Field(default=60, ge=1, le=120)
    model_max_output_tokens: int = Field(default=4096, ge=64, le=4096)
    model_report_max_output_tokens: int = Field(default=8192, ge=64, le=8192)
    model_pricing_verified_on: date = date(2026, 10, 26)
    speech_model_directory: Path = BACKEND_DIR / "data" / "models" / "whisper-small"
    speech_temporary_directory: Path = BACKEND_DIR / "data" / "speech-tmp"
    maintenance_directory: Path = BACKEND_DIR / "data" / "maintenance"
    backup_directory: Path = BACKEND_DIR.parent / "backups"
    speech_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    speech_max_seconds: int = Field(default=180, ge=10, le=600)
    speech_timeout_seconds: int = Field(default=120, ge=10, le=300)
    generation_workers: int = Field(default=2, ge=1, le=4)

    @model_validator(mode="after")
    def validate_server_settings(self):
        if self.secret_key and (
            len(self.secret_key.get_secret_value()) < 32
            or self.secret_key.get_secret_value().startswith("REPLACE_")
        ):
            raise ValueError("secret_key must contain at least 32 non-placeholder characters")
        if self.database_url and self.environment != "test":
            if not self.database_url.get_secret_value().startswith("mysql+pymysql://"):
                raise ValueError("The application requires the dedicated MySQL database")
        if "*" in self.allowed_origins:
            raise ValueError("Credentialed endpoints require explicit allowed origins")
        if self.environment == "production":
            if not self.cookie_secure or not self.database_url or not self.secret_key:
                raise ValueError("Production requires secure cookies, database and secret_key")
            if not all(origin.startswith("https://") for origin in self.allowed_origins):
                raise ValueError("Production origins must use HTTPS")
        return self
