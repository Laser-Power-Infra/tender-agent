"""Self-check for intelligence v2 (agents/intelligence/v2): ReAct reasoning agents with a search tool.

Run: .venv/Scripts/python.exe tests/test_v2_agent.py
Needs no network: search subgraph and chat model are stubbed.
"""
import os

for _k, _v in {
    "DATABASE_URL": "postgresql://u:p@localhost:5432/d",
    "QDRANT_URL": "http://localhost:9001",
    "QDRANT_API_KEY": "x",
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672",
    "TEMP_DIR": "./tmp",
    "OPENAI_API_KEY": "sk-test",
}.items():
    os.environ.setdefault(_k, _v)


def test_graph_picks_v2_run_task():
    from lib.core.config import settings

    settings.intelligence_version = "v2"
    from agents.intelligence import graph as g
    from agents.intelligence.v2.run_task import run_task as v2

    compiled = g.build_intelligence_graph()
    assert compiled.builder.nodes["run_task"].runnable.func is v2
    settings.intelligence_version = "v1"
    from agents.intelligence.nodes.run_task import run_task as v1

    assert g.build_intelligence_graph().builder.nodes["run_task"].runnable.func is v1


def _hit(i, text="EMD Rs 1,00,000 by DD", rerank=0.9):
    h = {"id": f"c{i}", "score": 0.4, "text": text, "payload": {"document_name": "nit.pdf", "page_no": i}}
    if rerank is not None:
        h["rerank_score"] = rerank
    return h


def _stub_search(valid, status="searched", error=None, raise_=None):
    import agents.intelligence.v2.tools as t

    class G:
        def invoke(self, payload):
            if raise_:
                raise raise_
            return {"valid": valid, "status": status, "error": error}

    t.get_search_graph = lambda: G()


def test_tool_formats_hits_and_collects_sources():
    from agents.intelligence.v2.tools import make_search_tool

    _stub_search([_hit(1), _hit(2, rerank=None)])
    sources = []
    out = make_search_tool("T1", sources).invoke({"query": "emd amount", "keywords": ["EMD"]})
    assert "[nit.pdf, page 1]" in out and "[nit.pdf, page 2]" in out and "\n---\n" in out, out
    assert [s["chunk_id"] for s in sources] == ["c1", "c2"]
    assert sources[0]["score"] == 0.9 and sources[1]["score"] == 0.4  # rerank_score else qdrant score
    assert set(sources[0]) == {"chunk_id", "document", "text", "score", "source_file", "page"}


def test_tool_empty_query_skips_search():
    from agents.intelligence.v2.tools import make_search_tool

    _stub_search([], raise_=AssertionError("must not search"))
    assert make_search_tool("T1", []).invoke({"query": "  "}) == "no relevant chunks"


def test_tool_no_hits():
    from agents.intelligence.v2.tools import make_search_tool

    _stub_search([])
    assert make_search_tool("T1", []).invoke({"query": "emd"}) == "no relevant chunks"


def test_tool_search_failed_status():
    from agents.intelligence.v2.tools import make_search_tool

    _stub_search([], status="failed", error="qdrant down")
    assert make_search_tool("T1", []).invoke({"query": "emd"}).startswith("search failed: qdrant down")


def test_tool_search_raises():
    from agents.intelligence.v2.tools import make_search_tool

    _stub_search([], raise_=RuntimeError("boom"))
    assert make_search_tool("T1", []).invoke({"query": "emd"}).startswith("search failed: RuntimeError: boom")


if __name__ == "__main__":
    test_graph_picks_v2_run_task()
    test_tool_formats_hits_and_collects_sources()
    test_tool_empty_query_skips_search()
    test_tool_no_hits()
    test_tool_search_failed_status()
    test_tool_search_raises()
    print("v2 agent self-check passed")
