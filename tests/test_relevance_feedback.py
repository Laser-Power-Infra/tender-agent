"""Self-check for relevance feedback: same-tender feedback first, company filter, rule in prompt.

Run: uv run python -m tests.test_relevance_feedback
No network: Qdrant, embeddings and the LLM are faked.
"""
from types import SimpleNamespace

import relevance.nodes.analyze as an
import relevance.nodes.search as se
from relevance.nodes.feedback import feedback_point_id

REF, CO = "T-1", "gmd"
OWN = feedback_point_id(REF, CO)


class FakeQdrant:
    def __init__(self):
        self.query_kwargs = None

    def retrieve(self, collection_name, ids, with_payload):
        assert ids == [OWN]
        return [SimpleNamespace(id=OWN, score=0, payload={"text": "x", "brief": "own brief", "feedback": "verdict: not relevant"})]

    def query_points(self, **kw):
        self.query_kwargs = kw
        own_dupe = SimpleNamespace(id=OWN, score=0.99, payload={"text": "x"})
        other = SimpleNamespace(id="b", score=0.8, payload={"text": "y", "brief": "other brief", "feedback": "relevant"})
        return SimpleNamespace(points=[own_dupe, other])


def test_search_puts_same_tender_first_and_filters_company():
    fake = FakeQdrant()
    se.qdrant = fake
    se.ensure_collection = lambda name: name
    se.get_dense = lambda: SimpleNamespace(embed_query=lambda q: [0.1])
    out = se.search({"reference_no": REF, "company": CO, "extra": {"tenderbrief": "supply of valves"}})
    hits = out["hits"]
    assert [h["same_tender"] for h in hits] == [True, False], hits  # own point not duplicated
    assert fake.query_kwargs["query_filter"].must[0].match.value == CO
    assert "score_threshold" in fake.query_kwargs
    return hits


def test_analyze_sends_rule_and_tags():
    seen = {}

    class LLM:
        def with_structured_output(self, _):
            return self

        def invoke(self, msgs):
            seen["msgs"] = msgs
            return an.RelevanceVerdict(valid=False, reason="same tender feedback")

    an.get_llm = lambda: LLM()

    class Ctx:
        def __enter__(self):
            return SimpleNamespace(add=lambda _: None, commit=lambda: None)

        def __exit__(self, *a):
            return False

    an.get_session_context = Ctx
    hits = test_search_puts_same_tender_first_and_filters_company()
    out = an.analyze({"reference_no": REF, "company": CO, "extra": {"tenderbrief": "supply of valves"}, "hits": hits})
    assert out["status"] == "analyzed", out
    system, human = seen["msgs"][0][1], seen["msgs"][1][1]
    assert an.FEEDBACK_RULE in system
    assert "[SAME TENDER]\nbrief: own brief\nhuman feedback: verdict: not relevant" in human
    assert "[similar tender, score 0.80]" in human
    # high cosine must not promote a different tender's feedback to a scope match
    assert "NEAR-DUPLICATE" not in an._format_hit({"score": 0.79, "text": "y", "payload": {}})
    assert "NEAR-DUPLICATE" in an._format_hit({"score": 0.93, "text": "y", "payload": {}})


if __name__ == "__main__":
    test_search_puts_same_tender_first_and_filters_company()
    test_analyze_sends_rule_and_tags()
    print("relevance feedback ok")
