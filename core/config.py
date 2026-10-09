from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # postgres
    database_url: str
    db_echo: bool = False


    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        if not isinstance(v, str):
            return v
        v = v.strip().strip('"').strip("'")
        # legacy postgres:// -> postgresql+psycopg://
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+psycopg://", 1)
        elif v.startswith("postgresql://") and "postgresql+psycopg://" not in v:
            v = v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    # qdrant
    qdrant_url:str
    qdrant_api_key:str

    @field_validator("qdrant_api_key", mode="before")
    @classmethod
    def validate_qdrant_api_key(cls, v:str)-> str:
        if v is None or not v.strip():
            raise ValueError("QDRANT_API_KEY missing")
        return v.strip()

    # rabbitmq
    rabbitmq_url:str

    @field_validator("rabbitmq_url", mode="before")
    @classmethod
    def validate_rabbitmq_url(cls, v:str)->str:
        if v is None and not v.strip():
            raise ValueError("RABBITMQ_URL missing")
        return v.strip()

    temp_dir:str
    @field_validator("temp_dir", mode="before")
    @classmethod
    def is_exist_temp_dir(cls, v:str)-> str:
        if v is None and not v.strip():
            raise ValueError("TEMP_DIR is not set")
        return v.strip()

    # langfuse observability (disabled by default, enable with LANGFUSE_ENABLED=true)
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None

    # google drive oauth (3-env, no file dependency)
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_refresh_token: str | None = None
    google_oauth_token_uri: str = "https://oauth2.googleapis.com/token"

    # openai embeddings (dense)
    openai_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_batch_size: int = 100

    # qdrant collection + chunking
    qdrant_collection: str = "tender_chunks"
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # relevance feedback vector collection (per-agent, not per-message)
    relevance_collection: str = "relevance"
    # cosine floor for similar-tender feedback; same-tender feedback ignores it. tune from search logs
    relevance_min_score: float = 0.5
    # brief-to-brief cosine for a near-duplicate tender (same project, other town ~0.93) whose feedback may decide.
    # cable supply-vs-laying / supply-vs-stringing pairs measured 0.77-0.79, so keep this above 0.8
    relevance_override_score: float = 0.9

    # reranker (cross-encoder) — ponytail: env-driven, no hardcode in nodes
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_device: str = "cpu"

    # chat llm — ponytail: one knob for every node, was hardcoded gpt-4o-mini in six files
    chat_model: str = "gpt-5.6-luna"

    # webhook — notify external system after final synthesis; empty disables
    ted_webhook_url: str | None = None

    # relevance webhook — company-wise endpoints, empty disables
    laser_url: str | None = None
    gmd_url: str | None = None

    # ponytail: one strip validator for every optional string, was the same four lines x4
    @field_validator(
        "google_oauth_client_id",
        "google_oauth_client_secret",
        "google_oauth_refresh_token",
        "google_oauth_token_uri",
        "openai_api_key",
        "embedding_model",
        "qdrant_collection",
        "relevance_collection",
        "rerank_model",
        "rerank_device",
        "chat_model",
        "ted_webhook_url",
        "laser_url",
        "gmd_url",
        mode="before",
    )
    @classmethod
    def strip_quoted(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip().strip('"').strip("'").strip() or None
        return v


settings = Settings()  # type: ignore[call-arg]
