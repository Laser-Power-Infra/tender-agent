import logging

from intelligence.state import is_done
from intelligence.subagents.specialized.state import SpecializedState
from intelligence.subagents.search.graph import get_search_graph

logger = logging.getLogger(__name__)

# ponytail: query pairs are independent — dedup happens after retrieval, so nothing forces an order.
# batch() runs them through a thread pool. 4, not 8: the intelligence graph now fans 8 sections out at
# once, so 8x8 in-flight searches would swamp the CPU reranker. 8 tasks x 4 = the same ~32 as before.
_SEARCH_CONCURRENCY = 4

# ponytail: per document, not per section. A section holds up to 25 documents; a global cap of 21
# silently dropped the lowest-ranked ones while the synthesis prompt demanded a row for every one.
_HITS_PER_DOC = 2

# runaway guard only — 25 documents x 2 hits is the real ceiling
_MAX_RESULTS = 120

_SOURCE_TEXT_CHARS = 500


def _provenance(hit: dict) -> tuple[str, object]:
    """(source_file, page) from the Qdrant payload. Written by ingestion/nodes/chunk_embed_push.py,
    which stores both snake_case and camelCase keys."""
    payload = hit.get("payload") or {}
    source_file = payload.get("document_name") or payload.get("documentName") or "unknown file"
    page = payload.get("page_no", payload.get("pageNo"))
    return source_file, page


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

    # (document, search payload). The payload stays exactly the SearchState keys — no extra fields.
    plan: list[tuple[str, dict]] = []
    for item in query_pairs:
        query = (item.get("query") or "").strip()
        if not query:
            continue
        keywords = item.get("keywords") or item.get("keyword") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        plan.append(
            (item.get("document") or "", {"query": query, "keywords": keywords, "reference_no": reference_no})
        )

    if not plan:
        logger.warning("execute_search skip, every query_pair was blank ref=%s", reference_no)
        return {"search_results": [], "sources": [], "status": "no_plan", "error": None}

    outs = get_search_graph().batch(
        [payload for _, payload in plan],
        config={"max_concurrency": _SEARCH_CONCURRENCY},
        return_exceptions=True,  # one bad query must not lose the other results
    )

    results: list[dict] = []
    sources: list[dict] = []
    # ponytail: the search subgraph's status and error used to be written and never read, so a dead
    # qdrant looked identical to a tender that mentions nothing
    failures: list[str] = []
    # ponytail: no cross-pair dedup. Once `document` is the join key it is actively wrong — document 7
    # would lose its best chunk because document 2 claimed it first. Two documents citing the same
    # clause is the correct answer. Within a pair, distinct hit ids already guarantee uniqueness.
    for (document, payload), out in zip(plan, outs):
        query = payload["query"]
        if isinstance(out, Exception):
            logger.error("specialized search item failed query=%r error=%s ref=%s", query[:80], out, reference_no)
            failures.append(f"{type(out).__name__}: {out}")
            continue
        if not is_done(out.get("status")):
            err = out.get("error") or out.get("status") or "search failed"
            logger.error("specialized search failed query=%r status=%s error=%s ref=%s", query[:80], out.get("status"), err, reference_no)
            failures.append(str(err))
            continue
        # ponytail: rerank already applied the relevance threshold and sorted by score. Re-filtering
        # on rerank_score > 0 here dropped the entire qdrant fallback path — those items have no
        # rerank_score, defaulted to 0, and every document silently lost half its hits.
        # rerank owns relevance, this owns per-document capping.
        top = (out.get("valid") or [])[:_HITS_PER_DOC]
        for v in top:
            source_file, page = _provenance(v)
            results.append({"document": document, "query": query, "keywords": payload["keywords"], "hit": v})
            sources.append(
                {
                    "chunk_id": v.get("id"),
                    "document": document,
                    "text": (v.get("text") or "")[:_SOURCE_TEXT_CHARS],
                    # None on the qdrant fallback path, so fall back to the qdrant score
                    "score": v.get("rerank_score") if v.get("rerank_score") is not None else v.get("score"),
                    "source_file": source_file,
                    "page": page,
                }
            )
        logger.info("specialized search item done query=%r valid=%s kept=%s ref=%s", query[:80], len(out.get("valid") or []), len(top), reference_no)

    # ponytail: checklist order preserved so synthesize groups deterministically; the cap is a guard,
    # not a filter — sorting by score here would scramble the document grouping.
    if failures and not results:
        err = f"every search failed ({len(failures)}/{len(plan)}), first: {failures[0]}"
        logger.error("execute_search ref=%s %s", reference_no, err)
        return {"search_results": [], "sources": [], "status": "failed", "error": err}
    if failures:
        logger.warning("execute_search partial ref=%s failed=%s/%s first=%s", reference_no, len(failures), len(plan), failures[0])

    if len(results) > _MAX_RESULTS:
        # a cap that hides what it removed reads as full coverage in the logs
        logger.warning("search results capped ref=%s kept=%s dropped=%s", reference_no, _MAX_RESULTS, len(results) - _MAX_RESULTS)
    results = results[:_MAX_RESULTS]
    sources = sources[:_MAX_RESULTS]
    logger.info("specialized execute_search done ref=%s pairs=%s results=%s", reference_no, len(plan), len(results))
    return {"search_results": results, "sources": sources, "status": "searched" if results else "no_results", "error": None}
