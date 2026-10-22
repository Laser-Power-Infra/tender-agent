import logging
from typing import Any

from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from lib.core.config import settings
from agents.relevance.nodes.feedback import brief_of, feedback_point_id
from lib.vector.embeddings import get_dense
from lib.vector.qdrant import ensure_collection, qdrant

logger = logging.getLogger(__name__)


def _hit(p, same_tender: bool) -> dict[str, Any]:
    payload = getattr(p, "payload", {}) or {}
    return {
        "id": str(getattr(p, "id", "")),
        "score": float(getattr(p, "score", 0) or 0),
        "text": payload.get("text") or "",
        "payload": payload,
        "same_tender": same_tender,
    }


def search(state: dict[str, Any]) -> dict[str, Any]:
    ref = (state.get("reference_no") or "").strip()
    company = state.get("company")
    brief = brief_of(state.get("extra") or {})

    if not brief:
        err = "tenderbrief missing in extra"
        logger.error("%s ref=%s", err, ref)
        return {"hits": [], "status": "failed", "error": err}

    try:
        dense = get_dense().embed_query(brief)
    except Exception as e:
        err = f"dense embed failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"hits": [], "status": "failed", "error": err}

    try:
        coll = ensure_collection(name=settings.relevance_collection)
        # feedback on this exact tender always comes first, whatever its similarity
        own_id = feedback_point_id(ref, company)
        hits = [_hit(p, True) for p in qdrant.retrieve(collection_name=coll, ids=[own_id], with_payload=True)]
        res = qdrant.query_points(
            collection_name=coll,
            query=dense,
            using="dense",
            query_filter=Filter(must=[FieldCondition(key="company", match=MatchValue(value=company))]),
            limit=5,
            score_threshold=settings.relevance_min_score,
            with_payload=True,
        )
        hits += [_hit(p, False) for p in (res.points if hasattr(res, "points") else []) if str(p.id) != own_id]
        logger.info("relevance search ref=%s company=%s collection=%s hits=%s", ref, company, coll, len(hits))
        for i, h in enumerate(hits):
            logger.info(
                "relevance hit #%s ref=%s same_tender=%s score=%.4f id=%s text=%r",
                i, ref, h["same_tender"], h["score"], h["id"], h["text"][:300],
            )
        if not hits:
            logger.warning("relevance search returned 0 feedback chunks ref=%s collection=%s", ref, coll)
        return {"hits": hits, "status": "searched", "error": None}
    except Exception as e:
        err = f"qdrant query failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"hits": [], "status": "failed", "error": err}
