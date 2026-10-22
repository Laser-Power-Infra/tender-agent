"""Self-check for the category node: feedback override, LLM fallback for work tenders, no LLM for supply.

Run: uv run python -m tests.test_category
No network: Qdrant, embeddings and the LLM are faked.
"""
from types import SimpleNamespace

import agents.relevance.nodes.category as ca

CO = "laser"


def fake_qdrant(own=None, similar=()):
    return SimpleNamespace(
        retrieve=lambda **kw: [SimpleNamespace(id="own", score=0, payload=own)] if own else [],
        query_points=lambda **kw: SimpleNamespace(points=[SimpleNamespace(id=f"s{i}", score=s, payload=p) for i, (s, p) in enumerate(similar)]),
    )


def setup(qd, pick=None):
    calls = []

    class LLM:
        def with_structured_output(self, _):
            return self

        def invoke(self, msgs):
            calls.append(msgs)
            return ca.CategoryPick(category=pick, reason="x")

    ca.qdrant = qd
    ca.ensure_collection = lambda name: name
    ca.get_dense = lambda: SimpleNamespace(embed_query=lambda q: [0.1])
    ca.get_llm = lambda: LLM()
    return calls


def run(brief, incoming="cables_conductors"):
    return ca.categorise({"reference_no": "T-1", "company": CO, "category": incoming, "extra": {"tenderbrief": brief}})


def test_same_tender_feedback_beats_rules():
    setup(fake_qdrant(own={"category": "railways"}))
    assert run("sitc of 132 kv line") == {"category": "railways"}


def test_similar_feedback_does_not_decide():
    setup(fake_qdrant(similar=[(0.7, {"brief": "b", "category": "railways"})]))
    assert run("sitc of 132 kv line") == {"category": "power_transmission"}


def test_work_tender_without_rule_goes_to_llm_with_feedback_examples():
    calls = setup(fake_qdrant(similar=[(0.7, {"brief": "building work", "category": "water_distribution"})]), pick="water_distribution")
    assert run("construction of community hall") == {"category": "water_distribution"}
    assert "category: water_distribution" in calls[0][1][1]


def test_no_llm_for_supply_or_trusted_incoming():
    calls = setup(fake_qdrant(), pick="solar")
    assert run("supply of water pipes") == {}
    assert run("construction of community hall", incoming="solar") == {}
    assert calls == []


def test_search_failure_falls_back_to_rules():
    def boom(**kw):
        raise RuntimeError("down")

    setup(SimpleNamespace(retrieve=boom, query_points=boom))
    assert run("sitc of 11 kv line") == {"category": "power_distribution"}


def test_category_without_prompt_is_dropped():
    setup(fake_qdrant())
    assert ca.categorise({"company": "gmd", "category": "valve", "extra": {"tenderbrief": "sitc of 132 kv line"}}) == {}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("category ok")
