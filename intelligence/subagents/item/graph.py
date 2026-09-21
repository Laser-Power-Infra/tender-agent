import logging

from langgraph.graph import END, START, StateGraph

from intelligence.subagents.item.nodes.decide import decide
from intelligence.subagents.item.nodes.generate_query import generate_query
from intelligence.subagents.item.nodes.hybrid_search import hybrid_search
from intelligence.subagents.item.state import ItemState

logger = logging.getLogger(__name__)


def build_item_graph(checkpointer=None):
    graph = StateGraph(ItemState)
    graph.add_node("generate_query", generate_query)
    graph.add_node("hybrid_search", hybrid_search)
    graph.add_node("decide", decide)
    graph.add_edge(START, "generate_query")
    graph.add_edge("generate_query", "hybrid_search")
    graph.add_edge("hybrid_search", "decide")
    graph.add_edge("decide", END)
    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    logger.info("Item subagent graph compiled checkpointer=%s", bool(checkpointer))
    return compiled


_item_graph = None


def get_item_graph():
    global _item_graph
    if _item_graph is None:
        _item_graph = build_item_graph()
    return _item_graph