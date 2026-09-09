from datetime import datetime

from sqlalchemy import Text, func
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=255)
    name: str = Field(max_length=100)
    hashed_password: str = Field(max_length=255)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": func.now()},
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": func.now(), "onupdate": func.now()},
    )


class Document(SQLModel, table=True):
    __tablename__ = "documents"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    document_id: str = Field(index=True, unique=True, max_length=36)
    external_document_id: int | None = Field(default=None, index=True)
    job_id: str = Field(index=True, max_length=100)
    reference_no: str = Field(index=True, max_length=100)
    document_tag: str = Field(default="", max_length=100)
    document_name: str | None = Field(default=None, max_length=512)
    original_url: str = Field(max_length=2048)
    file_url: str = Field(max_length=2048)
    file_path: str | None = Field(default=None, max_length=1024)
    status: str = Field(default="initialized", max_length=50)
    error: str | None = Field(default=None, sa_type=Text)
    total_pages: int | None = Field(default=None)
    chunk_count: int | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": func.now()},
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": func.now(), "onupdate": func.now()},
    )


class DocumentPage(SQLModel, table=True):
    __tablename__ = "document_pages"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    document_id: str = Field(index=True, max_length=36, foreign_key="documents.document_id")
    external_document_id: int | None = Field(default=None, index=True)
    job_id: str = Field(index=True, max_length=100)
    reference_no: str | None = Field(default=None, index=True, max_length=100)
    document_tag: str | None = Field(default=None, max_length=100)
    page_no: int = Field(index=True)
    total_pages: int | None = Field(default=None)
    markdown: str | None = Field(default=None, sa_type=Text)
    text: str | None = Field(default=None, sa_type=Text)
    status: str = Field(default="parsed", max_length=50)
    error: str | None = Field(default=None, sa_type=Text)
    original_url: str | None = Field(default=None, max_length=2048)
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": func.now()},
    )
