from langgraph.graph import END, START, StateGraph

from ingestion.state import IngestionState

def build_ingestion_graph():
    graph = StateGraph(IngestionState)

    return graph.compile()