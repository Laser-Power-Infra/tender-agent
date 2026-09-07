import logging

from langgraph.graph import END, START, StateGraph

from ingestion.state import IngestionState
from ingestion.nodes.initialize_document import initialize_document
from ingestion.nodes.download_document import download_document
from ingestion.nodes.prepare_pages import prepare_pages
from ingestion.nodes.parse_single_page import parse_single_page

logger = logging.getLogger(__name__)


def _fanout_pages(state: IngestionState):
    from langgraph.types import Send

    total = state.get("total_pages") or 0
    if total <= 0:
        return []
    # Send one parallel task per page; pass doc_cache to avoid N re-converts
    return [
        Send(
            "parse_single_page",
            {
                "page_no": i,
                "file_path": state.get("file_path"),
                "doc_cache": state.get("doc_cache"),
                "total_pages": total,
                "original_url": state.get("original_url") or state.get("file_url"),
                "reference_no": state.get("reference_no"),
                "document_tag": state.get("document_tag"),
                "document_name": state.get("document_name"),
                "document_id": state.get("document_id"),
                "job_id": state.get("job_id"),
            },
        )
        for i in range(1, total + 1)
    ]


def _aggregate_pages(state: IngestionState) -> dict:
    pages = state.get("parsed_pages") or []
    # reducer may have unsorted order
    pages = sorted(pages, key=lambda x: x.get("page_no", 0))
    ok = sum(1 for p in pages if p.get("status") == "parsed")
    fail = len(pages) - ok
    status = "parsed" if fail == 0 else "partial" if ok > 0 else "failed"
    logger.info("aggregate total=%s ok=%s fail=%s ref=%s tag=%s", len(pages), ok, fail, state.get("reference_no"), state.get("document_tag"))
    return {"parsed_pages": pages, "status": status}


def build_ingestion_graph():
    logger.info("Building ingestion graph: initialize_document -> download_document -> prepare_pages -> [parse_single_page x N]")
    graph = StateGraph(IngestionState)

    graph.add_node("initialize_document", initialize_document)
    graph.add_node("download_document", download_document)
    graph.add_node("prepare_pages", prepare_pages)
    graph.add_node("parse_single_page", parse_single_page)
    graph.add_node("aggregate_pages", _aggregate_pages)

    graph.add_edge(START, "initialize_document")
    graph.add_edge("initialize_document", "download_document")
    graph.add_edge("download_document", "prepare_pages")
    graph.add_conditional_edges("prepare_pages", _fanout_pages, ["parse_single_page"])
    graph.add_edge("parse_single_page", "aggregate_pages")
    graph.add_edge("aggregate_pages", END)

    compiled = graph.compile()
    logger.info("Ingestion graph compiled")  # ponytail: INFO only, add DEBUG per-node if verbose needed
    return compiled