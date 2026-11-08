from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SOP_", extra="ignore", env_file=REPO_ROOT / ".env", env_ignore_empty=True
    )

    extractor_model: str = "claude-haiku-5-5"
    responder_model: str = "claude-sonnet-5-5"
    responder_mode: Literal["llm", "template"] = "llm"
    today_override: date | None = Field(default=None, validation_alias="SOP_TODAY")
    session_ttl_seconds: int = 3600
    max_sessions: int = 500
    max_message_chars: int = 2000
    fixtures_dir: Path = REPO_ROOT / "apps" / "insurance_claims" / "fixtures"
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    def today(self) -> date:
        return self.today_override or date.today()
