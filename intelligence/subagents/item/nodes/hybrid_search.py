import logging

from qdrant_client.http.models import Prefetch, SparseVector

from intelligence.subagents.item.state import ItemState
from vector.embeddings import get_dense, get_sparse
from vector.qdrant import ensure_collection, qdrant

logger = logging.getLogger(__name__)

_ITEM_COLLECTION = "item-knowledge"
_TOP_K = 5


def extract_item_name(text: str) -> str:
    """Pull the item name out of the stored text payload ("item name: X, item category: Y")."""
    head = (text or "")[:60]
    if "item name:" in head:
        name = text.split("item name:", 1)[1].split(", item category:", 1)[0].strip()
        return name
    return (text or "").strip()


def _search_query(query: str) -> tuple[list[dict], str | None]:
    """One hybrid search; returns (hits, error)."""
    try:
        dense = get_dense().embed_query(query)
    except Exception as e:
        return [], f"dense embed failed: {type(e).__name__}: {e}"

    sparse_vec = None
    try:
        sparse_emb = get_sparse()
        if sparse_emb is not None:
            raw = list(sparse_emb.embed([query]))[0]
            indices = raw.indices.tolist() if hasattr(raw.indices, "tolist") else list(raw.indices)
            values = raw.values.tolist() if hasattr(raw.values, "tolist") else list(raw.values)
            if indices and values:
                sparse_vec = SparseVector(indices=indices, values=values)
    except Exception as e:
        logger.warning("sparse embed failed, dense-only: %s", e)

    # ponytail: payload has no category field — category text lives inside `text` — so no filter,
    # similarity over the whole collection; add a real category payload field when it grows
    try:
        coll = ensure_collection(_ITEM_COLLECTION)
        try:
            if sparse_vec is not None:
                res = qdrant.query_points(
                    collection_name=coll,
                    prefetch=[
                        Prefetch(query=dense, using="dense", limit=20),
                        Prefetch(query=sparse_vec, using="sparse", limit=20),
                    ],
                    query=dense,
                    using="dense",
                    limit=_TOP_K,
                    with_payload=True,
                )
                points = res.points if hasattr(res, "points") else []
            else:
                raise RuntimeError("no sparse")
        except Exception as e:
            logger.info("hybrid prefetch fallback to dense search: %s", e)
            res = qdrant.query_points(
                collection_name=coll,
                query=dense,
                using="dense",
                limit=_TOP_K,
                with_payload=True,
            )
            points = res.points if hasattr(res, "points") else []
    except Exception as e:
        return [], f"qdrant query failed: {type(e).__name__}: {e}"

    hits = []
    for p in points:
        payload = getattr(p, "payload", {}) or {}
        text = payload.get("text") or ""
        hits.append(
            {
                "name": extract_item_name(text),
                "text": text[:400],
                "score": float(getattr(p, "score", 0) or 0),
            }
        )
    return hits, None


def hybrid_search(state: ItemState) -> dict:
    category = (state.get("item_category") or "").strip()
    queries = [q.strip() for q in (state.get("queries") or []) if (q or "").strip()]
    if not queries:
        err = "queries required"
        logger.error("item hybrid_search %s", err)
        return {"hits": [], "status": "failed", "error": err}

    logger.info("item hybrid_search category=%r queries=%s", category, queries)
    # merge across queries: keep best score per distinct item name
    merged: dict[str, dict] = {}
    errors: list[str] = []
    for q in queries:
        hits, err = _search_query(q)
        if err:
            errors.append(err)
            logger.error("item hybrid_search query=%r failed error=%s", q, err)
            continue
        for h in hits:
            prev = merged.get(h["name"])
            if prev is None or h["score"] > prev["score"]:
                merged[h["name"]] = h
        logger.info("item hybrid_search query=%r hits=%s", q, len(hits))

    hits = sorted(merged.values(), key=lambda h: h["score"], reverse=True)[:_TOP_K]
    if not hits:
        status = "failed" if errors else "no_hits"
        return {"hits": [], "status": status, "error": (errors[0] if errors else None)}
    logger.info("item hybrid_search category=%r merged hits=%s", category, len(hits))
    return {"hits": hits, "status": "searched", "error": None}