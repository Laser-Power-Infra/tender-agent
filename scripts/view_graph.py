import sys
from pathlib import Path

# ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from intelligence.graph import build_intelligence_graph
from intelligence.subagents.search.graph import build_search_graph

if __name__ == "__main__":
    # intelligence main graph — build_* already compiled
    graph = build_intelligence_graph()
    print("=== Intelligence Graph ===")
    print(graph.get_graph().draw_mermaid())

    # search subagent graph
    search_graph = build_search_graph()
    print("\n=== Search Subagent Graph ===")
    print(search_graph.get_graph().draw_mermaid())
