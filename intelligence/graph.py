import logging

from langgraph.graph import END, START, StateGraph

from intelligence.state import IntelligenceState
from intelligence.nodes.execute_search import execute_search
from intelligence.nodes.generate_search_plan import generate_search_plan

logger = logging.getLogger(__name__)


def build_intelligence_graph(checkpointer=None):
    logger.info("Building intelligence graph checkpointer=%s", bool(checkpointer))
    graph = StateGraph(IntelligenceState)
    graph.add_node("generate_search_plan", generate_search_plan)
    graph.add_node("execute_search", execute_search)
    graph.add_edge(START, "generate_search_plan")
    graph.add_edge("generate_search_plan", "execute_search")
    graph.add_edge("execute_search", END)
    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    logger.info("Intelligence graph compiled checkpointer=%s", bool(checkpointer))
    return compiled
