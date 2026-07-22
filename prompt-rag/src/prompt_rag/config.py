from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROMPT_RAG_",
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    source_path: Path = PROJECT_DIR.parent / "knowledge-base" / "normalized" / "prompts.jsonl"
    db_path: Path = PROJECT_DIR / "data" / "prompt_rag.db"
    auto_ingest: bool = True

    embedding_provider: str = "none"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dimensions: int = Field(default=1024, ge=1, le=4096)
    embedding_batch_size: int = Field(default=10, ge=1, le=512)
    embedding_text_max_chars: int = Field(default=6000, ge=500, le=50000)
    model_cache_dir: Path = PROJECT_DIR / "data" / "models"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    translation_provider: str = "mimo"
    mimo_config_path: Path = Path(
        "D:/mycode/LangChain/rag_system/config/llm_config.json"
    )

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    admin_password: str = ""
    admin_session_secret: str = ""
    admin_session_hours: int = Field(default=12, ge=1, le=168)

    host: str = "127.0.0.1"
    port: int = Field(default=8010, ge=1, le=65535)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    legacy_frontend_path: Path = PROJECT_DIR / "web" / "index.html"
    legacy_static_dir: Path = PROJECT_DIR / "web" / "static"
    studio_dist_dir: Path = PROJECT_DIR / "web-v2" / "dist"

    lexical_weight: float = Field(default=0.60, ge=0, le=1)
    dense_weight: float = Field(default=0.40, ge=0, le=1)
    rrf_k: int = Field(default=60, ge=1, le=500)

    def prepare_paths(self) -> None:
        if not self.source_path.is_absolute():
            self.source_path = (PROJECT_DIR / self.source_path).resolve()
        if not self.db_path.is_absolute():
            self.db_path = (PROJECT_DIR / self.db_path).resolve()
        if not self.model_cache_dir.is_absolute():
            self.model_cache_dir = (PROJECT_DIR / self.model_cache_dir).resolve()
        if not self.legacy_frontend_path.is_absolute():
            self.legacy_frontend_path = (
                PROJECT_DIR / self.legacy_frontend_path
            ).resolve()
        if not self.legacy_static_dir.is_absolute():
            self.legacy_static_dir = (PROJECT_DIR / self.legacy_static_dir).resolve()
        if not self.studio_dist_dir.is_absolute():
            self.studio_dist_dir = (PROJECT_DIR / self.studio_dist_dir).resolve()
        if not self.mimo_config_path.is_absolute():
            self.mimo_config_path = (PROJECT_DIR / self.mimo_config_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.model_cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_paths()
    return settings
