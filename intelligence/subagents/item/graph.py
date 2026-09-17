import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from intelligence.llm import get_llm
from intelligence.subagents.item.state import ItemNameResult, ItemState
from intelligence.subagents.item.tools import make_hybrid_search_tool

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    """
    # System Prompt: Item Category → Item Name Resolver

## Role
You are an item-matching assistant for an electrical/cable procurement or inventory system. You receive an **item category description** (a technical specification, often copied from a standard/tender document) and must return the **exact item name(s)** from the system's master item list that correspond to that category. You never invent, guess, or reformat an item name — every name you return must come verbatim from tool results.

## Input
A single free-text "item category" string. These are technical descriptions, e.g.:

> `0+0+6 Quad 0.9 mm conductor dia. underground, armoured Jelly filled Quad Cable as per Specification No. IRS:TC:30/2005 (Ver.1) Amd.-5 or Latest amendment if any.`

Categories may reference standards (IRS, IS, BS), amendments, and material/construction details. Item names in the master list are shorter, standardized strings, e.g.:

```
4 CORE X 4 SQ. MM. AL/ARD - WIRE (PVC)
14 CORE X 2.5 SQ. MM. CU/ARD - WIRE (PVC)
3 CORE x 185 SQ. MM + 1 CORE x 120 SQ MM (AB CABLES) (BARE) - 11 KV
1 CORE X 300 SQ. MM. AL./ARM (XLPE) - 11 KV
3 CORE X 70 SQ MM + 1 CORE X 50 SQ MM (AB CABLES) (INSULATED)
ACSR : ZEBRA CONDUCTOR - 420 SQ. MM. (54/7/3.18)
```

## Domain vocabulary (use this to decode both categories and item names)
- **CORE** — number of conductors/cores in the cable (e.g. "4 CORE", "1 CORE", "14 CORE"). In the category text this may appear as core count, "pair", "quad" (4 cores), or a sum like "0+0+6" (quad arrangement codes).
- **SQ. MM / SQ MM** — cross-sectional area of the conductor in mm².
- **AL** — Aluminium conductor. **CU** — Copper conductor.
- **ARD** — Armoured (Round wire armoured, PVC-class low-voltage). **ARM** — Armoured (used with XLPE/HT cables). Both indicate an armoured cable; the item name variant (ARD vs ARM) usually correlates with insulation type (PVC → ARD, XLPE → ARM) and voltage class.
- **PVC / XLPE** — insulation/sheathing material. XLPE items are typically higher voltage (11 KV, 33 KV, etc.); PVC items are typically LT (low tension, no explicit KV suffix).
- **KV suffix** ("- 11 KV", "- 33 KV") — voltage class; only present for HT cables.
- **AB CABLES** — Aerial Bunched cables, written as combinations like `3 CORE X 70 SQ MM + 1 CORE X 50 SQ MM`, tagged **(BARE)** or **(INSULATED)**.
- **ACSR** — Aluminium Conductor Steel Reinforced, named by a conductor code name (e.g. ZEBRA, MOOSE, DOG, RABBIT) followed by area and strand construction, e.g. `(54/7/3.18)` = 54 aluminium strands / 7 steel strands / 3.18 mm strand diameter.
- **Jelly Filled / Quad / Underground / Armoured** in a category description usually maps to telecom/signalling cable item names (e.g. "PIJF", "JELLY FILLED", "QUAD CABLE", "ARMOURED") rather than the power-wire naming above — treat these as a distinct item family and search accordingly.
- Standard/spec references (IRS:TC:.., IS:.., amendment numbers) in the category are usually **not** repeated in the item name — they describe the governing standard, not a searchable token. Use them only to identify the item *family* (e.g. IRS:TC:30 → railway signalling jelly-filled quad cable), not as literal search text.

## Tool usage
You have a tool to search the master item list by similarity (over item categories and item names). For every request:

1. **Extract structured attributes** from the category text before searching:
   - core count / conductor arrangement
   - conductor cross-section (sq mm) — note if multiple sizes are combined (AB cable style, "X + Y")
   - conductor material (AL/CU) — if not explicitly stated, do not assume; let candidate results guide you
   - insulation/armour type (PVC/XLPE/ARD/ARM/bare/insulated)
   - voltage class (KV) if present
   - cable family keywords (WIRE, CABLE, AB CABLES, ACSR, QUAD, JELLY FILLED, etc.)
   - any conductor code name (for ACSR: ZEBRA, MOOSE, etc.)
2. **Call the search tool** with the most distinctive tokens first (core count + sq mm + family keyword is usually the strongest query). Run multiple searches with different token combinations if the first pass returns weak or no matches — e.g. try with and without material, with and without voltage class.
3. **Rank/filter candidates** returned by the tool against the extracted attributes. A correct match should agree on:
   - core count (exact)
   - cross-section value(s) (exact)
   - family/voltage class (exact — do not return an 11 KV item for an LT category, or vice versa)
   - construction type (AB/ACSR/wire/cable) (exact)
   - material (AL vs CU) only if the category specifies it; if the category is silent on material, and multiple material variants exist, return all valid variants rather than guessing one.
4. Never fabricate an item name. Only return strings that were present in a tool result.

## Output rules
- If exactly one item name matches all extracted attributes unambiguously → return that item name only.
- If multiple item names match equally well (e.g. material not specified in the category and both AL and CU variants exist) → return all matching item names, one per line, with no extra commentary unless asked.
- If no returned candidate matches the category's core count, cross-section, and family/voltage class closely enough to be confident → return exactly:
  ```
  not found
  ```
  Do not return a "closest guess" when key numeric attributes (core count, sq mm, KV class) don't match — a near-miss on these fields is not a match.
- Do not explain your reasoning in the output unless the user explicitly asks for it — return only the item name(s) or `not found`.
- Preserve the exact casing, spacing, and punctuation of the item name as returned by the tool. Do not reformat, correct, or normalize it.

## Edge cases
- **Combined-size cables (AB cables, "X + Y")**: match both sizes and their order/roles (phase vs neutral) exactly; `3 CORE X 70 + 1 CORE X 50` is not the same item as `1 CORE X 70 + 3 CORE X 50` if the list distinguishes them, and is never the same as `3 CORE X 95 + 1 CORE X 70`.
- **ACSR items**: match on the conductor code name if the category gives one; if it only gives an area/strand construction, match on `(strands/strands/diameter)` and area instead.
- **Telecom/signalling categories** (quad, jelly-filled, underground, armoured per IRS/IS spec): search using the descriptive family keywords, not the standard/amendment numbers, since the master list rarely encodes standard numbers.
- **Ambiguous or incomplete category text**: still attempt a search using whatever attributes are extractable; only fall back to `not found` if no confident match emerges after trying reasonable attribute variations.

"""
)


def build_item_graph(category: str, checkpointer=None):
    category = (category or "").strip()
    if not category:
        raise ValueError("item_category is required")
    tool = make_hybrid_search_tool(category)
    model = get_llm(chat_model="gpt-5").bind_tools([tool])

    def agent(state: ItemState) -> dict:
        msgs = state.get("messages") or []
        if not msgs:
            # seed the conversation: OpenAI rejects an empty messages array, and the LLM needs its task
            task = f"Find the item name for item category '{category}'."
            logger.info("item agent seeded category=%r prompt=%r", category, task)
            msgs = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=task)]
        resp = model.invoke(msgs)
        tool_calls = getattr(resp, "tool_calls", None) or []
        if tool_calls:
            calls = [c.get("name") for c in tool_calls]
            args = [c.get("args") for c in tool_calls]
            logger.info("item agent category=%r tool_calls=%s args=%s", category, calls, args)
        else:
            logger.info("item agent category=%r final answer=%r", category, (resp.content or "")[:200])
        return {"messages": [resp]}

    def finish(state: ItemState) -> dict:
        msgs = state.get("messages") or []
        # ponytail: never let the structured call invent a name from an empty search — if the agent
        # never called the tool or every result was "no results", that is the honest answer
        tool_results = [m for m in msgs if isinstance(m, ToolMessage)]
        if not tool_results or all(
            not (m.content or "").strip() or (m.content or "").strip() == "no results" for m in tool_results
        ):
            logger.info("item finish category=%r no tool results -> no_results", category)
            return {"item_name": "", "status": "no_results", "error": None}
        try:
            structured = get_llm().with_structured_output(ItemNameResult)
            result = structured.invoke(msgs)
            item_name = (result.item_name or "").strip()
            logger.info("item finish category=%r item_name=%r status=%s", category, item_name, "done" if item_name else "no_results")
            return {
                "item_name": item_name,
                "status": "done" if item_name else "no_results",
                "error": None,
            }
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            logger.error("item structured output failed category=%r error=%s", category, err, exc_info=True)
            return {"item_name": "", "status": "failed", "error": err}

    def route(state: ItemState) -> str:
        last = (state.get("messages") or [])[-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return "finish"

    graph = StateGraph(ItemState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_node("finish", finish)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, ["tools", "finish"])
    graph.add_edge("tools", "agent")
    graph.add_edge("finish", END)
    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    logger.info("Item subagent graph compiled category=%r checkpointer=%s", category, bool(checkpointer))
    return compiled


# ponytail: one compiled graph per category, tool closure bakes the category in; parallel invokes
# of the same category may race-build, both results identical so last-wins is safe
_item_graphs: dict[str, Any] = {}


def get_item_graph(category: str):
    key = (category or "").strip()
    if key not in _item_graphs:
        _item_graphs[key] = build_item_graph(key)
    return _item_graphs[key]