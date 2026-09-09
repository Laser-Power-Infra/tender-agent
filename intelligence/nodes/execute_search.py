import logging

from intelligence.state import IntelligenceState
from intelligence.subagents.search.graph import get_search_graph

logger = logging.getLogger(__name__)


def execute_search(state: IntelligenceState) -> dict:
    reference_no = (state.get("reference_no") or "").strip()
    search_plan: list[dict] = state.get("search_plan") or []

    if not search_plan:
        logger.warning("execute_search skip, search_plan empty ref=%s", reference_no)
        return {"search_results": [], "status": "no_plan", "error": None}

    results: list[dict] = []
    search_graph = get_search_graph()

    # ponytail: sequential loop O(n*m), no parallel until latency proves need
    for item in search_plan:
        query = (item.get("query") or "").strip()
        # generate_search_plan uses `keyword` singular; search subagent expects `keywords` plural
        keywords = item.get("keyword") or item.get("keywords") or []
        if not query:
            continue
        if isinstance(keywords, str):
            keywords = [keywords]
        try:
            out = search_graph.invoke({"query": query, "keywords": keywords, "reference_no": reference_no})
            valid = out.get("valid") or []
            for v in valid:
                # append with query context for traceability
                results.append({"query": query, "keywords": keywords, "hit": v})
            logger.info("search item done query=%r keywords=%s valid=%s ref=%s", query[:80], keywords, len(valid), reference_no)
        except Exception as e:
            logger.error("search item failed query=%r error=%s ref=%s", query[:80], e, reference_no, exc_info=True)

    # print output — ponytail: logger + stdout, no file/db sink until need
    print(f"[intelligence] reference_no={reference_no} search_results={len(results)}")
    for r in results:
        hit = r.get("hit") or {}
        print(f"  query={r.get('query')!r} score={hit.get('rerank_score'):.2f} text={hit.get('text','')[:200]!r}")

    logger.info("execute_search done ref=%s plan=%s results=%s", reference_no, len(search_plan), len(results))
    return {"search_results": results, "status": "searched" if results else "no_results", "error": None}
