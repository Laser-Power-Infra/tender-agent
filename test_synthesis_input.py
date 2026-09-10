"""Self-check for synthesize_final_result._agent_blocks: no raw chunk text, no agent silently lost.

Run: python test_synthesis_input.py
"""
import json
import sys
import types

# _agent_blocks is plain json/string work; stub the deps the module imports so no install is needed
_llm = types.ModuleType("intelligence.llm")
_llm.get_llm = lambda: None
sys.modules.setdefault("intelligence.llm", _llm)

if "pydantic" not in sys.modules:
    _pyd = types.ModuleType("pydantic")

    class _BaseModel:
        pass

    _pyd.BaseModel = _BaseModel
    _pyd.Field = lambda *a, **k: None
    sys.modules["pydantic"] = _pyd

from intelligence.nodes.synthesize_final_result import (  # noqa: E402
    _MAX_AGENT_CHARS,
    _agent_blocks,
    _drop_unclear,
)


def _envelope(agent, sources_chars):
    return {
        "task_id": f"{agent}_1",
        "agent": agent,
        "status": "success",
        "result": {"summary": f"{agent} findings"},
        "sources": [{"chunk_id": "c1", "text": "X" * sources_chars, "score": 1.0}] * 21,
        "error": None,
    }


def test_sources_never_reach_the_prompt():
    results = {"elig_1": _envelope("eligibility", 500)}
    out = _agent_blocks(results)
    assert "XXXX" not in out, "raw chunk text must not be sent to the synthesis LLM"
    assert "sources" not in out, out
    assert "eligibility findings" in out


def test_every_agent_survives():
    agents = ["company_document_finder", "reverse_auction", "eligibility", "important_dates", "financial_terms"]
    results = {f"{a}_1": _envelope(a, 500) for a in agents}
    out = _agent_blocks(results)
    for a in agents:
        assert f"### {a}_1" in out, f"{a} was dropped from the synthesis input"
        assert f"{a} findings" in out


def test_one_huge_result_only_truncates_itself():
    results = {
        "big_1": {"agent": "eligibility", "status": "success", "result": {"summary": "Y" * (_MAX_AGENT_CHARS * 3)}},
        "small_1": {"agent": "important_dates", "status": "success", "result": {"summary": "the deadline is 1 April"}},
    }
    out = _agent_blocks(results)
    assert "...[truncated]" in out
    assert "the deadline is 1 April" in out, "a later agent must not be lost to an earlier agent's size"


def test_unclear_rows_become_a_count():
    rows = [
        {"document": "PAN Card", "required": "Required", "evidence": "listed in eligibility"},
        {"document": "GST LUT", "required": "Unclear", "evidence": ""},
        {"document": "Trade Licence", "required": "Unclear", "evidence": ""},
    ]
    out = _drop_unclear({"results": rows})
    assert [r["document"] for r in out["results"]] == ["PAN Card"], out
    assert out["unclear_count"] == 2, out


def test_drop_unclear_leaves_other_agents_alone():
    # the analytical agents have no "results" list — their shape must survive untouched
    for value in ({"summary": "x", "criteria": ["a"]}, None, {}, {"results": "not a list"}):
        assert _drop_unclear(value) == value, value


def test_a_document_section_shrinks_in_the_final_prompt():
    rows = [{"document": f"Doc {i}", "required": "Unclear", "evidence": ""} for i in range(24)]
    rows.append({"document": "Doc 24", "required": "Required", "evidence": "mandatory"})
    out = _agent_blocks({"common.works_construction": {"agent": "common.works_construction", "status": "success", "result": {"results": rows}}})
    assert "Doc 24" in out and "mandatory" in out
    assert "Doc 3" not in out, "Unclear rows must not reach the final prompt"
    assert '"unclear_count": 24' in out, out


def test_each_block_is_valid_json():
    results = {"elig_1": _envelope("eligibility", 10)}
    body = _agent_blocks(results).split("\n", 1)[1]
    json.loads(body)  # raises if the old mid-JSON slice came back


if __name__ == "__main__":
    test_sources_never_reach_the_prompt()
    test_every_agent_survives()
    test_one_huge_result_only_truncates_itself()
    test_unclear_rows_become_a_count()
    test_drop_unclear_leaves_other_agents_alone()
    test_a_document_section_shrinks_in_the_final_prompt()
    test_each_block_is_valid_json()
    print("synthesis input self-check passed")
