"""Self-check for the item subagent: guards and name parsing.

Run: uv run python test_item_agent.py
Calls no network and no LLM: empty-input guards return before embedding/model calls.
"""
import intelligence.subagents.item.nodes.generate_query as gq
import intelligence.subagents.item.nodes.hybrid_search as hs


def test_extract_item_name_from_text_payload():
    text = "item name: 3 CORE X 300 SQ. MM. AL/ARM - WIRE (XLPE) - 33 KV, item category: 3 Core, 300 Sq mm"
    assert hs.extract_item_name(text) == "3 CORE X 300 SQ. MM. AL/ARM - WIRE (XLPE) - 33 KV"
    assert hs.extract_item_name("no marker text") == "no marker text"


def test_generate_query_empty_category_fails():
    out = gq.generate_query({"item_category": "   "})
    assert out["status"] == "failed"
    assert out["error"]


def test_hybrid_search_empty_queries_fails():
    out = hs.hybrid_search({"item_category": "Electrical", "queries": ["", "  "]})
    assert out["status"] == "failed"
    assert out["error"]
    out2 = hs.hybrid_search({"item_category": "Electrical"})
    assert out2["status"] == "failed"


if __name__ == "__main__":
    test_extract_item_name_from_text_payload()
    test_generate_query_empty_category_fails()
    test_hybrid_search_empty_queries_fails()
    print("item subagent self-check passed")