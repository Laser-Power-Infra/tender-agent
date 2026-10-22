from langgraph.graph import END, START, StateGraph

from agents.relevance.state import RelevanceState


def _route(state: dict) -> str:
    return state.get("payload_type") or "feedback"


def build_relevance_graph():
    from agents.relevance.nodes.analyze import analyze
    from agents.relevance.nodes.category import categorise
    from agents.relevance.nodes.feedback import embed_feedback
    from agents.relevance.nodes.search import search
    # Replaced by worker-level dispatch (core/webhook_dispatch.py). Uncomment to roll back.
    # from relevance.nodes.webhook import send_webhook

    g = StateGraph(RelevanceState)
    g.add_node("search", search)
    g.add_node("category", categorise)
    g.add_node("analysis", analyze)
    # g.add_node("webhook", send_webhook)
    g.add_node("feedback", embed_feedback)
    g.add_conditional_edges(
        START,
        _route,
        {"analysis": "search", "feedback": "feedback"},
    )
    g.add_edge("search", "category")
    g.add_edge("category", "analysis")
    # Rollback: restore these two edges and delete the direct edge below.
    # g.add_edge("analysis", "webhook")
    # g.add_edge("webhook", END)
    g.add_edge("analysis", END)
    g.add_edge("feedback", END)
    return g.compile()