import logging

from langgraph.graph import END, START, StateGraph

from intelligence.subagents.search.state import SearchState
from intelligence.subagents.search.nodes.hybrid_search import hybrid_search
from intelligence.subagents.search.nodes.rerank import rerank

logger = logging.getLogger(__name__)


def build_search_graph(checkpointer=None):
    # ponytail: no checkpointer needed for internal subagent; param kept for parity
    logger.info("Building search subagent graph checkpointer=%s", bool(checkpointer))
    graph = StateGraph(SearchState)
    graph.add_node("hybrid_search", hybrid_search)
    graph.add_node("rerank", rerank)
    graph.add_edge(START, "hybrid_search")
    graph.add_edge("hybrid_search", "rerank")
    graph.add_edge("rerank", END)
    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    logger.info("Search subagent graph compiled")
    return compiled


# ponytail: sync helper for parent agent — single invoke, no worker queue
_search_graph = None


def get_search_graph():
    global _search_graph
    if _search_graph is None:
        _search_graph = build_search_graph()
    return _search_graph
