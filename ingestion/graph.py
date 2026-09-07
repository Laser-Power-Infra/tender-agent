import logging
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ingestion.state import IngestionState
from ingestion.nodes.initialize_document import initialize_document
from ingestion.nodes.download_document import download_document
from ingestion.nodes.parse_document import parse_pdf, parse_docx, parse_xlsx, parse_txt
from ingestion.nodes.chunk_embed_push import chunk_embed_push
from ingestion.nodes.cleanup import cleanup

logger = logging.getLogger(__name__)


def route_by_ext(state: IngestionState) -> str:
    """
    Conditional router for filetype branching.
    Uses file_path suffix lowercased; maps aliases.
    # ponytail: default pdf for missing/unknown suffix; node itself fails if truly unsupported
    """
    fp = state.get("file_path") or ""
    ext = Path(fp).suffix.lower().strip()
    if not ext:
        # fallback: try document_name
        dn = state.get("document_name") or ""
        ext = Path(dn).suffix.lower().strip()
    if ext == ".txt":
        return "parse_txt"
    if ext in (".xlsx", ".xls", ".csv"):
        return "parse_xlsx"
    if ext in (".docx", ".doc"):
        return "parse_docx"
    if ext == ".pdf":
        return "parse_pdf"
    # unknown or empty -> default pdf branch (docling handles many types) else fail
    # ponytail: explicit failed branch only when unsupported reports appear
    return "parse_pdf"


def build_ingestion_graph():
    logger.info("Building ingestion graph: initialize -> download -> {pdf|docx|xlsx|txt} -> chunk -> cleanup")
    graph = StateGraph(IngestionState)

    graph.add_node("initialize_document", initialize_document)
    graph.add_node("download_document", download_document)
    graph.add_node("parse_pdf", parse_pdf)
    graph.add_node("parse_docx", parse_docx)
    graph.add_node("parse_xlsx", parse_xlsx)
    graph.add_node("parse_txt", parse_txt)
    graph.add_node("chunk_embed_push", chunk_embed_push)
    graph.add_node("cleanup", cleanup)

    graph.add_edge(START, "initialize_document")
    graph.add_edge("initialize_document", "download_document")
    graph.add_conditional_edges(
        "download_document",
        route_by_ext,
        {
            "parse_pdf": "parse_pdf",
            "parse_docx": "parse_docx",
            "parse_xlsx": "parse_xlsx",
            "parse_txt": "parse_txt",
        },
    )
    for n in ("parse_pdf", "parse_docx", "parse_xlsx", "parse_txt"):
        graph.add_edge(n, "chunk_embed_push")
    graph.add_edge("chunk_embed_push", "cleanup")
    graph.add_edge("cleanup", END)

    compiled = graph.compile()
    logger.info("Ingestion graph compiled")  # ponytail: INFO only, add DEBUG per-node if verbose needed
    return compiled
