from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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
        


settings = Settings()  # type: ignore[call-arg]
