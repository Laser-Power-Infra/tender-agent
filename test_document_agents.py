"""Self-check for the 52 document-section agents.

Run: python test_document_agents.py
Stubs pydantic/langchain so it needs no installed deps.

The two checks that matter most are test_prompt_matches_the_checklist and
test_prompt_has_no_format_placeholders — they fail loudly if the generated prompt and the pipeline
that feeds it ever drift apart, which is the bug this whole change exists to stop repeating.
"""
import sys
import types


def _stub_deps():
    """pydantic + langchain_openai, enough for schemas.py and create_checklist.py to import."""
    if "pydantic" not in sys.modules:
        pyd = types.ModuleType("pydantic")

        class _BaseModel:
            def __init_subclass__(cls, **kw):
                super().__init_subclass__(**kw)

        pyd.BaseModel = _BaseModel
        pyd.Field = lambda *a, **k: None
        sys.modules["pydantic"] = pyd

    llm = types.ModuleType("intelligence.llm")
    llm.get_llm = lambda: None
    sys.modules.setdefault("intelligence.llm", llm)


_stub_deps()

from constants.tender_documents import TENDER_DOCUMENTS  # noqa: E402
from intelligence.nodes.create_checklist import AVAILABLE_AGENTS, create_checklist  # noqa: E402
from intelligence.subagents.specialized.document_agents import (  # noqa: E402
    DOCUMENT_AGENTS,
    SECTION_QUERIES,
    STATIC_QUERIES,
    _keywords,
    agents_for_tender_type,
)
from intelligence.subagents.specialized.prompts import AGENT_PROMPTS, SYNTHESIS_PROMPT  # noqa: E402
from intelligence.subagents.specialized.schemas import (  # noqa: E402
    AGENT_OUTPUT_MODELS,
    BaseSynthesizeDocumentOutput,
)


def test_one_agent_per_inner_section():
    assert len(DOCUMENT_AGENTS) == 52, len(DOCUMENT_AGENTS)
    per_bucket = {b: sum(1 for a in DOCUMENT_AGENTS if a.startswith(b + ".")) for b in TENDER_DOCUMENTS}
    assert per_bucket == {"gem_only": 5, "non_gem_only": 8, "common": 39}, per_bucket
    assert all("." in a for a in DOCUMENT_AGENTS), "the dot is what keeps these disjoint from hand-written names"
    assert "common.gst" in DOCUMENT_AGENTS


def test_no_collision_with_the_hand_written_agents():
    assert not set(DOCUMENT_AGENTS) & set(AVAILABLE_AGENTS), "a section would shadow an analytical agent"
    assert not any("." in a for a in AVAILABLE_AGENTS)


def test_every_agent_is_fully_registered():
    for agent in DOCUMENT_AGENTS:
        assert agent in STATIC_QUERIES, f"{agent} would fall through to an LLM query call"
        assert agent in SYNTHESIS_PROMPT, f"{agent} would borrow the company prompt"
        assert agent in AGENT_PROMPTS, agent
        assert AGENT_OUTPUT_MODELS.get(agent) is BaseSynthesizeDocumentOutput, agent


def test_707_pairs_with_unique_join_keys():
    assert sum(len(v) for v in SECTION_QUERIES.values()) == 707
    for agent, pairs in SECTION_QUERIES.items():
        docs = [p["document"] for p in pairs]
        assert len(set(docs)) == len(docs), f"{agent} has a duplicate join key"
        for p in pairs:
            assert p["query"].strip(), p
            assert 1 <= len(p["keywords"]) <= 6, p
            assert p["document"] in p["keywords"][0], p


def test_prompt_matches_the_checklist():
    for agent, pairs in SECTION_QUERIES.items():
        prompt = SYNTHESIS_PROMPT[agent]
        assert f"exactly {len(pairs)} objects" in prompt, agent
        for p in pairs:
            assert p["document"] in prompt, f"{agent} prompt is missing {p['document']!r}"


def test_prompt_has_no_format_placeholders():
    # synthesize.py calls .format() when it sees either token, which would blow up on the JSON braces
    for agent in DOCUMENT_AGENTS:
        for prompt in (SYNTHESIS_PROMPT[agent], AGENT_PROMPTS[agent]):
            assert "{agent}" not in prompt and "{task_description}" not in prompt, agent


def test_keyword_derivation():
    assert "Trade License" in _keywords("Trade Licence"), "spelling twin missing"
    assert "MOA" in _keywords("Memorandum of Association (MOA)")
    assert "GSTIN" in _keywords("GST Registration Certificate")
    for doc in ("Cancelled Cheque", "Trade Licence", "Company PAN"):
        kws = _keywords(doc)
        assert kws[0] == doc, kws
        assert len(kws) == len(set(kws)), kws


def test_routing_is_bucket_plus_common():
    assert len(agents_for_tender_type("gem")) == 44
    assert len(agents_for_tender_type("non_gem")) == 47
    for unknown in ("", None, "garbage", "GEM_ONLY_BUT_TYPOED"):
        routed = agents_for_tender_type(unknown)
        assert len(routed) == 39, unknown
        assert all(a.startswith("common.") for a in routed), unknown
    # case and spacing absorbed
    assert len(agents_for_tender_type("  GeM ")) == 44


def test_checklist_is_deterministic_without_an_llm():
    # empty parsed_request: the analytical agents are skipped, the document sections still run
    out = create_checklist({"reference_no": "T123", "tender_type": "gem", "parsed_request": {}})
    checklist = out["checklist"]
    assert len(checklist) == 44, len(checklist)
    assert all(t["status"] == "pending" for t in checklist)
    ids = [t["task_id"] for t in checklist]
    assert len(set(ids)) == len(ids), "task_id must be unique — run_task keys agent_results by it"
    assert out["errors"], "skipping the analytical agents should be recorded, not silent"
    assert len(create_checklist({"reference_no": "T", "tender_type": "non_gem"})["checklist"]) == 47
    assert len(create_checklist({"reference_no": "T"})["checklist"]) == 39


if __name__ == "__main__":
    test_one_agent_per_inner_section()
    test_no_collision_with_the_hand_written_agents()
    test_every_agent_is_fully_registered()
    test_707_pairs_with_unique_join_keys()
    test_prompt_matches_the_checklist()
    test_prompt_has_no_format_placeholders()
    test_keyword_derivation()
    test_routing_is_bucket_plus_common()
    test_checklist_is_deterministic_without_an_llm()
    print("document agents self-check passed")
