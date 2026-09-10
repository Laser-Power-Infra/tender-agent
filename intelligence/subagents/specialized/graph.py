import logging

from langgraph.graph import END, START, StateGraph

from intelligence.subagents.specialized.state import SpecializedState
from intelligence.subagents.specialized.nodes.generate_queries import generate_queries
from intelligence.subagents.specialized.nodes.execute_search import execute_search
from intelligence.subagents.specialized.nodes.synthesize import synthesize

logger = logging.getLogger(__name__)


def build_specialized_graph(checkpointer=None):
    # ponytail: no checkpointer need for internal subagent; param kept for parity with search/intelligence graphs
    logger.info("Building specialized graph checkpointer=%s", bool(checkpointer))
    graph = StateGraph(SpecializedState)
    graph.add_node("generate_queries", generate_queries)
    graph.add_node("execute_search", execute_search)
    graph.add_node("synthesize", synthesize)
    graph.add_edge(START, "generate_queries")
    graph.add_edge("generate_queries", "execute_search")
    graph.add_edge("execute_search", "synthesize")
    graph.add_edge("synthesize", END)
    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    logger.info("Specialized graph compiled")
    return compiled


# ponytail: singleton compiled graph, single invoke no worker queue
_specialized_graph = None


def get_specialized_graph():
    global _specialized_graph
    if _specialized_graph is None:
        _specialized_graph = build_specialized_graph()
    return _specialized_graph
