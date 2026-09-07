import logging

from langgraph.graph import END, START, StateGraph

from ingestion.state import IngestionState
from ingestion.nodes.initialize_document import initialize_document
from ingestion.nodes.download_document import download_document
from ingestion.nodes.parse_document import parse_document

logger = logging.getLogger(__name__)


def build_ingestion_graph():
    logger.info("Building ingestion graph: initialize_document -> download_document -> parse_document")
    graph = StateGraph(IngestionState)

    graph.add_node("initialize_document", initialize_document)
    graph.add_node("download_document", download_document)
    graph.add_node("parse_document", parse_document)

    graph.add_edge(START, "initialize_document")
    graph.add_edge("initialize_document", "download_document")
    graph.add_edge("download_document", "parse_document")
    graph.add_edge("parse_document", END)

    compiled = graph.compile()
    logger.info("Ingestion graph compiled")  # ponytail: INFO only, add DEBUG per-node if verbose needed
    return compiled