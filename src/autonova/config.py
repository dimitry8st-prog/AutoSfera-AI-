from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "AutoSfera AI"
    app_version: str = "2.0.0"
    dealer_id: str = Field(default="main-salon", validation_alias="DEALER_ID")
    dealer_name: str = Field(default="AutoSfera Demo Salon", validation_alias="DEALER_NAME")
    database_path: Path = Field(
        default=ROOT_DIR / "data" / "autosfera.db",
        validation_alias="DATABASE_PATH",
    )
    knowledge_base_dir: Path = ROOT_DIR / "knowledge_base"
    prompts_dir: Path = ROOT_DIR / "prompts"
    logs_dir: Path = Field(default=ROOT_DIR / "logs", validation_alias="LOGS_DIR")
    dialogues_dir: Path = Field(
        default=ROOT_DIR / "data" / "dialogues",
        validation_alias="DIALOGUES_DIR",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    # LLM: mock by default for offline/tests; set LLM_MODE=openai to use API
    llm_mode: str = Field(default="mock", validation_alias="LLM_MODE")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_BASE_URL",
    )
    openai_model: str = Field(default="gpt-5.6", validation_alias="OPENAI_MODEL")

    rag_top_k: int = 6
    rag_min_score: float = 0.05


@lru_cache
def get_settings() -> Settings:
    return Settings()
