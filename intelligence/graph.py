import logging

from langgraph.graph import END, START, StateGraph

from intelligence.nodes.analyze_request import analyze_request
from intelligence.state import IntelligenceState

logger = logging.getLogger(__name__)


def build_intelligence_graph(checkpointer=None):
    logger.info("Building intelligence graph checkpointer=%s", bool(checkpointer))
    graph = StateGraph(IntelligenceState)
    graph.add_node("analyze_request", analyze_request)
    graph.add_edge(START, "analyze_request")
    graph.add_edge("analyze_request", END)
    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    logger.info("Intelligence graph compiled checkpointer=%s", bool(checkpointer))
    return compiled
