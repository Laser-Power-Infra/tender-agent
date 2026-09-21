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
    try:
        import pydantic  # noqa: F401  — real one when installed, so model validation is real
    except ImportError:
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
from intelligence.subagents.specialized.prompts import (  # noqa: E402
    _BUCKET_FOR_AGENT,
    AGENT_PROMPTS,
    SYNTHESIS_PROMPT,
)
from intelligence.subagents.specialized.query_schemas import QueryItem  # noqa: E402
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
    # ponytail: now only 4 active agents, not 52 sections — check active set
    for agent in AVAILABLE_AGENTS:
        assert agent in SYNTHESIS_PROMPT, f"{agent} missing synthesis prompt"
        assert agent in AGENT_OUTPUT_MODELS, f"{agent} missing output model"
        if agent in ("document_finder", "company_document_finder"):
            assert agent in STATIC_QUERIES, f"{agent} would fall through to an LLM query call"
        else:
            assert agent in AGENT_PROMPTS, f"{agent} missing query prompt"


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
    # legacy 52 section prompts removed — only check active agents that have section queries
    for agent, pairs in SECTION_QUERIES.items():
        if agent not in SYNTHESIS_PROMPT:
            continue
        prompt = SYNTHESIS_PROMPT[agent]
        assert f"exactly {len(pairs)} objects" in prompt, agent
        for p in pairs:
            assert p["document"] in prompt, f"{agent} prompt is missing {p['document']!r}"


def test_prompt_has_no_format_placeholders():
    # synthesize.py calls .format() when it sees either token, which would blow up on the JSON braces
    for agent in AVAILABLE_AGENTS:
        for prompt in (SYNTHESIS_PROMPT.get(agent, ""), AGENT_PROMPTS.get(agent, "")):
            if not prompt:
                continue
            assert "{agent}" not in prompt and "{task_description}" not in prompt, agent


def test_document_prompts_carry_their_bucket():
    # the three live document agents end on a bare "Documents:" header; the bucket is appended there
    for agent, bucket in _BUCKET_FOR_AGENT.items():
        documents = list(dict.fromkeys(d for section in TENDER_DOCUMENTS[bucket].values() for d in section))
        prompt = AGENT_PROMPTS[agent]
        listed = [line for line in prompt.splitlines() if line.startswith("- ")]
        # equality, not containment: a stale dedupe shows up here and nowhere else
        assert listed == [f"- {d}" for d in documents], f"{agent} listed {len(listed)} of {len(documents)}"
        assert prompt.index("Documents:") < prompt.index(f"- {documents[0]}"), f"{agent} list is above its header"


def test_document_prompts_do_not_leak_across_buckets():
    assert "- GeM Seller Registration" in AGENT_PROMPTS["gem_document_agent"]
    assert "- GeM Seller Registration" not in AGENT_PROMPTS["non_gem_document_agent"]
    assert "- GeM Seller Registration" not in AGENT_PROMPTS["common_document_agent"]
    assert "- Certificate of Incorporation" in AGENT_PROMPTS["common_document_agent"]
    assert "- Certificate of Incorporation" not in AGENT_PROMPTS["gem_document_agent"]
    assert "- Notice Inviting Tender (NIT)" in AGENT_PROMPTS["non_gem_document_agent"]
    assert "- Notice Inviting Tender (NIT)" not in AGENT_PROMPTS["gem_document_agent"]


def test_query_item_carries_the_join_key():
    # execute_search groups hits by `document`; without the field it was always ""
    assert QueryItem(document="PAN Card", query="q", keywords=["k"]).model_dump()["document"] == "PAN Card"
    # defaulted, so the parameter agents (reverse_auction, basic_details, emd_agent) still validate
    assert QueryItem(query="q", keywords=["k"]).model_dump()["document"] == ""


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
    # GEM vs NON_GEM only: GEM→gem+common+3, else→non_gem+common+3
    out = create_checklist({"reference_no": "T123", "tender_type": "GEM", "parsed_request": {}})
    checklist = out["checklist"]
    assert len(checklist) == 5, len(checklist)
    assert all(t["status"] == "pending" for t in checklist)
    assert {t["agent"] for t in checklist} == {"reverse_auction", "basic_details", "emd_agent", "gem_document_agent", "common_document_agent"}
    ids = [t["task_id"] for t in checklist]
    assert len(set(ids)) == len(ids), "task_id must be unique — run_task keys agent_results by it"
    assert {t["agent"] for t in create_checklist({"reference_no": "T", "tender_type": "NON_GEM"})["checklist"]} == {"reverse_auction", "basic_details", "emd_agent", "non_gem_document_agent", "common_document_agent"}
    assert len(create_checklist({"reference_no": "T", "tender_type": "gem"})["checklist"]) == 5


def test_unknown_tender_type_runs_common_only():
    # worker/job.py normalizes an unrecognized type to "" and documents it as unknown. Asserting
    # non-GeM would ask the tender 76 non-GeM-only document questions on no evidence.
    for unknown in ("", "   ", "garbage", None):
        agents = {t["agent"] for t in create_checklist({"reference_no": "T", "tender_type": unknown})["checklist"]}
        assert agents == {"reverse_auction", "basic_details", "emd_agent", "common_document_agent"}, unknown
        assert "non_gem_document_agent" not in agents, unknown
        assert "gem_document_agent" not in agents, unknown


if __name__ == "__main__":
    test_one_agent_per_inner_section()
    test_no_collision_with_the_hand_written_agents()
    test_every_agent_is_fully_registered()
    test_707_pairs_with_unique_join_keys()
    test_prompt_matches_the_checklist()
    test_prompt_has_no_format_placeholders()
    test_document_prompts_carry_their_bucket()
    test_document_prompts_do_not_leak_across_buckets()
    test_query_item_carries_the_join_key()
    test_keyword_derivation()
    test_routing_is_bucket_plus_common()
    test_checklist_is_deterministic_without_an_llm()
    test_unknown_tender_type_runs_common_only()
    print("document agents self-check passed")
