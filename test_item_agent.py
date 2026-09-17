"""Self-check for the item subagent: tool guard and graph factory validation.

Run: uv run python test_item_agent.py
Calls no network: empty-query paths return before embed, category validation raises before LLM init.
"""
import intelligence.subagents.item.tools as t
import intelligence.subagents.item.graph as g


def test_empty_query_returns_no_results():
    tool = t.make_hybrid_search_tool("Electrical")
    assert tool.invoke({"query": ""}) == "no results"
    assert tool.invoke({"query": "   "}) == "no results"


def test_tool_name_and_description_present():
    tool = t.make_hybrid_search_tool("Electrical")
    assert tool.name == "hybrid_search"
    assert tool.description


def test_extract_item_name_from_text_payload():
    text = "item name: 3 CORE X 300 SQ. MM. AL/ARM - WIRE (XLPE) - 33 KV, item category: 3 Core, 300 Sq mm"
    assert t.extract_item_name(text) == "3 CORE X 300 SQ. MM. AL/ARM - WIRE (XLPE) - 33 KV"
    assert t.extract_item_name("no marker text") == "no marker text"


def test_empty_category_rejected():
    try:
        g.get_item_graph("   ")
    except ValueError:
        pass
    else:
        raise AssertionError("empty category must raise, not build an unbounded tool")


if __name__ == "__main__":
    test_empty_query_returns_no_results()
    test_tool_name_and_description_present()
    test_extract_item_name_from_text_payload()
    test_empty_category_rejected()
    print("item subagent self-check passed")