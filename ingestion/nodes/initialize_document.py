from pathlib import Path
from uuid import uuid4

from ingestion.state import IngestionState
from core.config import settings



TEMP_DIR = Path(settings.temp_dir)


def initialize_document(state: IngestionState) -> dict:
    """
    This node prepares the folders where we will store the files locally for ocr. It uses temp_dir env path.
    """
    job_id = state.get("job_id")
    file_url = state.get("file_url")

    if not job_id:
        raise ValueError("job_id is required")

    if not file_url:
        raise ValueError("file_url is required")

    document_id = str(uuid4())

    working_dir = TEMP_DIR / job_id
    working_dir.mkdir(parents=True, exist_ok=True)

    return {
        "document_id": document_id,
        "working_dir": str(working_dir),
        "current_page": 1,
        "status": "initialized",
        "error": None,
    }