from pathlib import Path
import httpx

from ingestion.state import IngestionState

def download_document(state:IngestionState)-> dict:
    file_url = state["file_url"]
    working_dir = Path(state["working_dir"])

    filename = Path(file_url.split("?"))