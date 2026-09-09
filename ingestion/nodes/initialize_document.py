from pathlib import Path
from uuid import uuid4

from ingestion.state import IngestionState
from core.config import settings



TEMP_DIR = Path(settings.temp_dir)


def initialize_document(state: IngestionState) -> dict:
    """
    This node prepares the folders where we will store the files locally for ocr. It uses temp_dir env path.
    Strict: reference_no, document_tag, original_url required.
    """
    job_id = state.get("job_id")
    file_url = state.get("file_url")
    original_url = state.get("original_url") or file_url
    reference_no = state.get("reference_no")
    document_tag = state.get("document_tag")
    document_name = state.get("document_name")
    external_document_id = state.get("external_document_id")

    if not job_id:
        raise ValueError("job_id is required")

    if not file_url:
        raise ValueError("file_url is required")

    if not original_url or not str(original_url).strip():
        raise ValueError("original_url is required (original document URL, not file_path)")

    if not reference_no or not str(reference_no).strip():
        raise ValueError("reference_no is required")

    if document_tag is None:
        document_tag = ""

    document_id = str(uuid4())

    working_dir = TEMP_DIR / job_id / document_id
    working_dir.mkdir(parents=True, exist_ok=True)

    return {
        "document_id": document_id,
        "external_document_id": external_document_id,
        "working_dir": str(working_dir),
        "original_url": str(original_url).strip(),
        "reference_no": str(reference_no).strip(),
        "document_tag": str(document_tag).strip() if str(document_tag).strip() else "",
        "document_name": str(document_name).strip() if document_name and str(document_name).strip() else None,
        "current_page": 1,
        "total_pages": 0,
        "parsed_pages": [],
        "status": "initialized",
        "error": None,
    }