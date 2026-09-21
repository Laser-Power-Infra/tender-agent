import logging

from intelligence.llm import get_llm
from intelligence.subagents.item.state import ItemNameResult, ItemState

logger = logging.getLogger(__name__)

# User-owned prompt — edit freely. Decision rules for mapping search hits to the final item name.
_DECIDE_SYSTEM_PROMPT = """
   
        # Role
        You receive (a) the original item category description and (b) a list of candidate item names returned by a hybrid search tool (already executed by another system — you do not run any search yourself). Your only job is to decide which single candidate, if any, correctly matches the category, or to say the match doesn't exist. You never call any tool.

        # Hard rule
        You may ONLY output one of the exact candidate strings you were given, or the literal text "not found". Never invent, edit, merge, reformat, correct spelling in, or partially quote an item name. If the right item isn't among the candidates, the answer is "not found" — not your closest guess.

        # Domain vocabulary (for interpreting both the category and the candidates)
        - CORE = conductor count. SQ. MM = conductor cross-section (mm²). Combined-size items (AB cables) list two sizes joined by "+".
        - AL = Aluminium, CU = Copper conductor.
        - ARD = armoured LT-class (pairs with PVC). ARM = armoured HT-class (pairs with XLPE).
        - PVC / XLPE = insulation type; XLPE items usually carry a KV suffix, PVC items usually don't.
        - AB CABLES = Aerial Bunched cable, tagged (BARE) or (INSULATED).
        - ACSR = Aluminium Conductor Steel Reinforced, identified by conductor code name (ZEBRA, MOOSE, etc.) and strand construction (e.g. 54/7/3.18).
        - Quad / jelly-filled / underground / armoured telecom-signalling categories belong to a separate cable family from the power wire/cable naming above.
        - Standard/amendment references in the category (IRS:TC:.., IS:.., "Amd.-5") never appear in item names — ignore them when comparing; they identify the family/spec, not a literal token to match.

        # How to decide
        1. From the category description, determine the required: item family/type (PVC wire / XLPE cable / ACSR / AB cable bare-or-insulated / telecom quad-jelly-filled / other), core count or conductor arrangement, cross-section size(s), material (AL/CU) if stated, voltage class (KV) if stated, and conductor code name if ACSR.
        2. Compare every candidate against these required attributes. A valid match must agree exactly on:
        - item family/type
        - core count (or ACSR conductor code)
        - cross-section size(s), including both sizes and their order for combined AB-cable sizes
        - voltage class, if the category specifies one
        - material (AL/CU), only if the category specifies one — if the category is silent on material and multiple candidates differ only by material, treat this as ambiguous (see below)
        3. If exactly one candidate satisfies all of these → output that candidate's exact string, nothing else.
        4. If the category doesn't specify material and more than one otherwise-identical candidate differs only by AL vs CU → output all those candidates as a list, exact strings, nothing else.
        5. If no candidate agrees on the required family/type + core count + cross-section (+ KV where applicable) → output exactly: ["not found"]
        6. Do not explain your reasoning, do not restate the category, do not add commentary — output only the final item name(s) or "not found".

        # Input you will receive
        - Category: <the original free-text category description>
        - Candidates: <list of item name strings returned by the search tool>

        # Output
        A JSON list of exact candidate strings (include multiple only if genuinely tied on an unspecified attribute), or ["not found"] if no match exists. Never include anything else.

        """


def _render(hits: list[dict]) -> str:
    lines = []
    for h in hits:
        lines.append(f"- {h.get('name')} (score {(h.get('score') or 0):.3f}): {h.get('text')}")
    return "\n".join(lines)


def decide(state: ItemState) -> dict:
    category = (state.get("item_category") or "").strip()
    queries = state.get("queries") or []
    hits = state.get("hits") or []

    if not hits:
        logger.info("item decide category=%r no hits -> no_results", category)
        return {"item_names": [], "status": "no_results", "error": None}

    try:
        structured = get_llm(chat_model="gpt-5.6-luna").with_structured_output(ItemNameResult)
        result = structured.invoke(
            [
                ("system", _DECIDE_SYSTEM_PROMPT),
                (
                    "human",
                    f"item category: {category}\nsearch queries: {queries}\nsearch results:\n{_render(hits)}",
                ),
            ]
        )
        item_names = [n.strip() for n in (result.item_names or []) if n.strip()]
        # prompt says the model may answer exactly "not found" — map that to an empty result
        if len(item_names) == 1 and item_names[0].lower() == "not found":
            logger.info("item decide category=%r model said not found", category)
            return {"item_names": [], "status": "no_results", "error": None}
        logger.info("item decide category=%r item_names=%r", category, item_names)
        return {"item_names": item_names, "status": "done" if item_names else "no_results", "error": None}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("item decide failed category=%r error=%s", category, err, exc_info=True)
        return {"item_names": [], "status": "failed", "error": err}


        