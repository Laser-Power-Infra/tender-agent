from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import text

from core.config import settings

# Normalize to psycopg driver: postgresql+psycopg://
# SQLModel.create_engine wraps sqlalchemy.create_engine (future=True)
engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
)


def create_db_and_tables() -> None:
    """Create all tables registered via SQLModel.metadata.

    Import models inside function to avoid circular imports and ensure
    metadata is populated before create_all (see SQLModel docs: from . import models).
    """
    from database import models as _models  # noqa: F401  # ensure User is imported

    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI-compatible dependency - yields a Session and auto-closes."""
    with Session(engine) as session:
        yield session


def get_session_context():
    """Context-manager style for workers/scripts: with get_session_context() as session."""
    return Session(engine)


def check_connection() -> bool:
    """Lightweight health check - executes SELECT 1 via psycopg."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.commit()
    return True
