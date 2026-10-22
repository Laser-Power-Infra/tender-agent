from langgraph.graph import END, START, StateGraph

from agents.performance_cert.state import PerformanceCertState


def build_performance_cert_graph():
    from agents.performance_cert.nodes.compare import compare
    from agents.performance_cert.nodes.decide import decide
    from agents.performance_cert.nodes.details import details
    from agents.performance_cert.nodes.extract import extract
    from agents.performance_cert.nodes.lookup import lookup

    g = StateGraph(PerformanceCertState)
    g.add_node("extract", extract)
    g.add_node("details", details)
    g.add_node("lookup", lookup)
    g.add_node("compare", compare)
    g.add_node("decide", decide)
    g.add_edge(START, "extract")
    g.add_edge("extract", "details")
    g.add_edge("details", "lookup")
    g.add_edge("lookup", "compare")
    g.add_edge("compare", "decide")
    g.add_edge("decide", END)
    return g.compile()
