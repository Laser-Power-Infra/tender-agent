import logging

from intelligence.subagents.specialized.state import SpecializedState
from intelligence.subagents.search.graph import get_search_graph

logger = logging.getLogger(__name__)


def execute_search(state: SpecializedState) -> dict:
    reference_no = (state.get("reference_no") or "").strip()
    query_pairs: list[dict] = state.get("query_pairs") or []

    if not reference_no:
        err = "reference_no required, search not executed"
        logger.error(err)
        return {"search_results": [], "sources": [], "status": "failed", "error": err}
    if not query_pairs:
        logger.warning("execute_search skip, no query_pairs ref=%s", reference_no)
        return {"search_results": [], "sources": [], "status": "no_plan", "error": None}

    search_graph = get_search_graph()
    results: list[dict] = []
    sources: list[dict] = []

    # ponytail: per-pair 3 solid hits, sequential dedup, 7 queries*3=21 pool for 20 docs
    seen: set[str] = set()
    for item in query_pairs:
        query = (item.get("query") or "").strip()
        keywords = item.get("keywords") or item.get("keyword") or []
        if not query:
            continue
        if isinstance(keywords, str):
            keywords = [keywords]
        try:
            out = search_graph.invoke({"query": query, "keywords": keywords, "reference_no": reference_no})
            valid = out.get("valid") or []
            # ponytail: solid 3 filter — rerank_score >0 threshold, slice 3 max per pair
            valid = sorted(valid, key=lambda x: x.get("rerank_score", 0), reverse=True)
            solid = [v for v in valid if v.get("rerank_score", 0) > 0]
            top = (solid[:3] if solid else valid[:1]) if valid else []
            top = top[:3]
            for v in top:
                vid = str(v.get("id") or "")
                if vid and vid in seen:
                    continue
                if vid:
                    seen.add(vid)
                results.append({"query": query, "keywords": keywords, "hit": v})
                sources.append({"chunk_id": v.get("id"), "text": (v.get("text") or "")[:500], "score": v.get("rerank_score")})
            logger.info("specialized search item done query=%r valid=%s kept=%s ref=%s", query[:80], len(valid), len(top), reference_no)
        except Exception as e:
            logger.error("specialized search item failed query=%r error=%s ref=%s", query[:80], e, reference_no, exc_info=True)

    # cap 21 deduped sorted by rerank_score desc — ponytail: 7*3=21 natural cap
    results.sort(key=lambda x: (x.get("hit") or {}).get("rerank_score", 0), reverse=True)
    sources.sort(key=lambda x: x.get("score", 0), reverse=True)
    results = results[:21]
    sources = sources[:21]
    logger.info("specialized execute_search done ref=%s pairs=%s results=%s deduped", reference_no, len(query_pairs), len(results))
    return {"search_results": results, "sources": sources, "status": "searched" if results else "no_results", "error": None}
