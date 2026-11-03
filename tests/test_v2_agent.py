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


def test_prompts_cover_reasoning_agents_only():
    from agents.intelligence.subagents.specialized.schemas import AGENT_OUTPUT_MODELS
    from agents.intelligence.v2.agent import _RECURSION_LIMIT, V2_AGENTS
    from agents.intelligence.v2.prompts import AGENT_PROMPTS

    assert V2_AGENTS == {"reverse_auction", "basic_details", "emd_agent", "qualification_requirement_finder"}
    assert _RECURSION_LIMIT == 12
    for name, p in AGENT_PROMPTS.items():
        assert "{reference_no}" in p and "search_tender" in p and "stop" in p.lower(), name
        p.format(reference_no="T1")  # only placeholder
        for field in AGENT_OUTPUT_MODELS[name].model_fields:
            if field not in ("summary", "evidence"):
                assert field in p, f"{name} prompt missing field {field}"


def _fake_model(*msgs, infinite=None):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class Fake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):  # the base raises NotImplementedError
            return self

    return Fake(messages=infinite if infinite is not None else iter(msgs))


def _tool_call(query, i=1):
    from langchain_core.messages import AIMessage

    return AIMessage(content="", tool_calls=[{"name": "search_tender", "args": {"query": query, "keywords": ["EMD"]}, "id": f"t{i}"}])


def test_build_agent_runs_tool_loop():
    from langchain_core.messages import AIMessage
    from agents.intelligence.v2 import agent as a

    _stub_search([_hit(1)])
    sources = []
    g = a.build_agent("emd_agent", "T1", sources, model=_fake_model(_tool_call("emd amount"), AIMessage(content="EMD is Rs 1,00,000 by DD.")))
    last = None
    for last in g.stream({"messages": [("human", "Analyse tender T1")]}, stream_mode="values"):
        pass
    assert len(sources) == 1
    assert sum(1 for m in last["messages"] if m.type == "tool") == 1


def _fake_llm(result=None, raise_=None):
    import agents.intelligence.v2.run_task as r

    class S:
        calls = 0
        last_msgs = None

        def invoke(self, msgs):
            S.calls += 1
            S.last_msgs = list(msgs)
            if raise_:
                raise raise_
            return result

    class L:
        def with_structured_output(self, model):
            return S()

    r.get_llm = lambda: L()
    return S


def _state(agent):
    return {"reference_no": "T1", "task": {"task_id": agent, "agent": agent, "status": "pending"}, "agent": agent}


def test_run_task_success_envelope():
    from langchain_core.messages import AIMessage
    import agents.intelligence.v2.run_task as r
    from agents.intelligence.subagents.specialized.schemas import EMDAgentOutput

    _stub_search([_hit(1)])
    r._MODEL = _fake_model(_tool_call("emd amount"), AIMessage(content="done"))
    S = _fake_llm(EMDAgentOutput(emdAmount="Rs 1,00,000"))
    out = r.run_task(_state("emd_agent"))
    env = out["agent_results"]["emd_agent"]
    assert env["status"] == "success" and env["error"] is None, env
    assert env["result"]["emdAmount"] == "Rs 1,00,000" and len(env["sources"]) == 1
    assert out["checklist"][0]["status"] == "success" and out["errors"] == []
    assert S.calls == 1
    assert set(env) == {"task_id", "agent", "status", "result", "sources", "error"}
    # the finalize call carries the agent's rules, not just the transcript
    from agents.intelligence.v2.prompts import AGENT_PROMPTS

    assert S.last_msgs[0] == ("system", AGENT_PROMPTS["emd_agent"].format(reference_no="T1")), S.last_msgs[0]
    assert S.last_msgs[-1][0] == "human"


def test_tool_dedupes_repeated_chunks():
    from agents.intelligence.v2.tools import make_search_tool

    _stub_search([_hit(1), _hit(2)])
    sources = []
    t = make_search_tool("T1", sources)
    t.invoke({"query": "emd amount"})
    t.invoke({"query": "earnest money"})
    assert [s["chunk_id"] for s in sources] == ["c1", "c2"]


def test_responses_llm_does_not_store():
    from lib.core.llm import get_llm

    llm = get_llm("x", use_responses_api=True)
    assert llm.store is False and "reasoning.encrypted_content" in (llm.include or [])
    assert get_llm("x").store is None


def test_run_task_no_tool_calls_still_success():
    from langchain_core.messages import AIMessage
    import agents.intelligence.v2.run_task as r
    from agents.intelligence.subagents.specialized.schemas import EMDAgentOutput

    _stub_search([_hit(1)])
    r._MODEL = _fake_model(AIMessage(content="nothing"))
    S = _fake_llm(EMDAgentOutput())
    env = r.run_task(_state("emd_agent"))["agent_results"]["emd_agent"]
    assert env["status"] == "success" and env["sources"] == [] and S.calls == 1


def test_run_task_recursion_limit_partial():
    import itertools
    import agents.intelligence.v2.run_task as r
    from agents.intelligence.subagents.specialized.schemas import EMDAgentOutput

    _stub_search([_hit(1)])
    r._MODEL = _fake_model(infinite=(_tool_call(f"q{i}", i) for i in itertools.count()))
    S = _fake_llm(EMDAgentOutput(emdAmount="partial"))
    out = r.run_task(_state("emd_agent"))
    env = out["agent_results"]["emd_agent"]
    assert env["status"] == "partial", env
    assert env["error"].startswith("recursion limit 12 hit after"), env["error"]
    assert env["result"]["emdAmount"] == "partial" and S.calls == 1
    assert len(env["sources"]) >= 1
    assert out["checklist"][0]["status"] == "success"  # partial is degraded, not failed


def test_run_task_finalize_raises_is_failed():
    from langchain_core.messages import AIMessage
    import agents.intelligence.v2.run_task as r

    _stub_search([_hit(1)])
    r._MODEL = _fake_model(AIMessage(content="nothing"))
    _fake_llm(raise_=RuntimeError("llm down"))
    out = r.run_task(_state("emd_agent"))
    env = out["agent_results"]["emd_agent"]
    assert env["status"] == "failed" and "llm down" in env["error"], env
    assert env["result"]["emdAmount"] == ""
    assert out["checklist"][0]["status"] == "failed" and len(out["errors"]) == 1


def test_run_task_document_agent_delegates_to_v1():
    import agents.intelligence.v2.run_task as r

    called = {}
    r.run_task_v1 = lambda state: called.setdefault("state", state) and {"checklist": [], "agent_results": {}, "errors": []}
    r.build_agent = lambda *a, **k: (_ for _ in ()).throw(AssertionError("v2 must not build"))
    r.run_task(_state("common_document_agent"))
    assert called["state"]["agent"] == "common_document_agent"
    called.clear()
    r.run_task(_state("nope"))
    assert called["state"]["agent"] == "nope"


if __name__ == "__main__":
    test_graph_picks_v2_run_task()
    test_prompts_cover_reasoning_agents_only()
    test_build_agent_runs_tool_loop()
    test_run_task_success_envelope()
    test_run_task_no_tool_calls_still_success()
    test_run_task_recursion_limit_partial()
    test_run_task_finalize_raises_is_failed()
    test_run_task_document_agent_delegates_to_v1()
    test_tool_dedupes_repeated_chunks()
    test_responses_llm_does_not_store()
    test_tool_formats_hits_and_collects_sources()
    test_tool_empty_query_skips_search()
    test_tool_no_hits()
    test_tool_search_failed_status()
    test_tool_search_raises()
    print("v2 agent self-check passed")
