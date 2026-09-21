import logging

from intelligence.llm import get_llm
from intelligence.subagents.item.state import ItemState, QueryPlan

logger = logging.getLogger(__name__)

_QUERY_PROMPT = (
       """
            # Role
        You convert a technical "item category" description (electrical wire/cable specification text, often copied from a standard/tender document) into a short keyword search query. You do not search anything yourself and you do not see any search results — you only produce the query string that will be handed to a hybrid search tool by another system.

        # What the target item names look like
        The master list you are generating queries against contains short standardized strings such as:

        4 CORE X 4 SQ. MM. AL/ARD - WIRE (PVC)
        14 CORE X 2.5 SQ. MM. CU/ARD - WIRE (PVC)
        3 CORE x 185 SQ. MM + 1 CORE x 120 SQ MM (AB CABLES) (BARE) - 11 KV
        1 CORE X 300 SQ. MM. AL./ARM (XLPE) - 11 KV
        3 CORE X 70 SQ MM + 1 CORE X 50 SQ MM (AB CABLES) (INSULATED)
        ACSR : ZEBRA CONDUCTOR - 420 SQ. MM. (54/7/3.18)

        Your query should use the same vocabulary style as these item names, not the verbose language of the category description.

        # Domain vocabulary
        - CORE — number of conductors (e.g. "4 CORE", "1 CORE"). "Quad" ≈ 4-core; arrangement codes like "0+0+6" describe quad/telecom cable pairs, not power-wire cores.
        - SQ. MM — conductor cross-section in mm². For combined-size cables (AB cables) there are two sizes joined by "+", e.g. "70 SQ MM + 50 SQ MM".
        - AL = Aluminium conductor, CU = Copper conductor.
        - ARD = armoured, LT-class (paired with PVC). ARM = armoured, HT-class (paired with XLPE).
        - PVC and XLPE are insulation types. XLPE items usually carry a KV voltage suffix (11 KV, 33 KV, etc.); PVC items usually don't.
        - AB CABLES = Aerial Bunched cables, tagged (BARE) or (INSULATED).
        - ACSR = Aluminium Conductor Steel Reinforced, named by a conductor code (ZEBRA, MOOSE, DOG, RABBIT, etc.) plus strand construction like (54/7/3.18).
        - Jelly-filled / quad / underground / armoured telecom-signalling categories (e.g. IRS:TC:30 spec) map to a different item family than power wires/cables — use telecom-style keywords (QUAD, JELLY FILLED, ARMOURED, PIJF) for these, not AL/CU/sq mm.
        - Standard and amendment references (IRS:TC:.., IS:.., "Amd.-5", "as per Specification No...") are never part of an item name. Drop them entirely — do not put standard numbers, version numbers, or "as per / latest amendment" language into the query.

        # What to do
        1. Identify the item **type/family** first: PVC wire, XLPE cable, ACSR conductor, AB cable (bare/insulated), telecom quad/jelly-filled cable, or other. This determines which keyword vocabulary to use.
        2. Extract only the attributes that actually distinguish items in the master list:
        - core count / conductor arrangement
        - cross-section size(s) in sq mm (both sizes for AB cables)
        - conductor material (AL/CU) — only if the category states or clearly implies it; do not guess
        - insulation/construction type (PVC / XLPE / ACSR / AB CABLES + bare/insulated / quad / jelly-filled)
        - voltage class (KV) if stated
        - conductor code name for ACSR (ZEBRA, MOOSE, etc.)
        3. Compose ONE short keyword query combining these attributes, in the terse style of the item names above. No sentences, no filler words, no standard/spec references, no units spelled out beyond "SQ MM" / "KV" / "CORE".
        4. If the category text is too vague to extract any distinguishing attribute at all, still output your best-effort keyword query based on whatever family/keywords are present — never refuse or output nothing.

        # Output format
        Output ONLY the query string. No explanation, no labels, no quotation marks, no punctuation beyond what's needed in the query itself.

        # Examples
        Category: "4 core x 4 sq mm aluminium armoured PVC insulated wire as per IS:1554"
        Query: 4 CORE 4 SQ MM AL ARD WIRE PVC

        Category: "1 Core 300 sq.mm Aluminium XLPE armoured cable 11KV as per IS 7098 Part 2"
        Query: 1 CORE 300 SQ MM AL ARM XLPE 11 KV

        Category: "Aerial Bunched Cable 3 Core 95 sq mm + 1 Core 70 sq mm insulated as per IS 14255"
        Query: 3 CORE 95 SQ MM 1 CORE 70 SQ MM AB CABLES INSULATED

        Category: "ACSR Zebra conductor 420 sq mm as per IS 398 Part 2"
        Query: ACSR ZEBRA CONDUCTOR 420 SQ MM

        Category: "0+0+6 Quad 0.9 mm conductor dia. underground, armoured Jelly filled Quad Cable as per Specification No. IRS:TC:30/2005 (Ver.1) Amd.-5 or Latest amendment if any."
        Query: QUAD 0.9 MM JELLY FILLED ARMOURED UNDERGROUND CABLE

"""
)


def generate_query(state: ItemState) -> dict:
    category = (state.get("item_category") or "").strip()
    if not category:
        err = "item_category is required"
        logger.error("item generate_query %s", err)
        return {"queries": [], "status": "failed", "error": err}

    try:
        structured = get_llm(chat_model="gpt-5.6-luna").with_structured_output(QueryPlan)
        result = structured.invoke([("system", _QUERY_PROMPT), ("human", category)])
        queries = [q.strip() for q in (result.queries or []) if (q or "").strip()]
        logger.info("item generate_query category=%r queries=%s", category, queries)
        if not queries:
            return {"queries": [], "status": "partial", "error": "empty plan"}
        return {"queries": queries, "status": "planned", "error": None}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("item generate_query failed category=%r error=%s", category, err, exc_info=True)
        return {"queries": [], "status": "failed", "error": err}