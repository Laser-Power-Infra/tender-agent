import logging

from langchain_core.tools import tool
from qdrant_client.http.models import Prefetch, SparseVector

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


def make_hybrid_search_tool(item_category: str):
    """Build the hybrid-search tool for one item category.

    Category is baked into the closure so the LLM only supplies queries — the tool cannot search
    outside its own category.
    """
    category = (item_category or "").strip()

    @tool
    def hybrid_search(query: str) -> str:
        """Hybrid dense+sparse search of the item-knowledge collection within the current item category.

        Args:
            query: what the item looks like (description, material, specification).
        Returns:
            Top matching item names with short snippets, or "no results".
        """
        q = (query or "").strip()
        if not q:
            logger.info("item hybrid_search category=%r empty query -> no results", category)
            return "no results"
        logger.info("item hybrid_search category=%r query=%r", category, q)
        try:
            dense = get_dense().embed_query(q)
        except Exception as e:
            return f"search failed: {type(e).__name__}: {e}"

        sparse_vec = None
        try:
            sparse_emb = get_sparse()
            if sparse_emb is not None:
                raw = list(sparse_emb.embed([q]))[0]
                indices = raw.indices.tolist() if hasattr(raw.indices, "tolist") else list(raw.indices)
                values = raw.values.tolist() if hasattr(raw.values, "tolist") else list(raw.values)
                if indices and values:
                    sparse_vec = SparseVector(indices=indices, values=values)
        except Exception as e:
            logger.warning("sparse embed failed, dense-only: %s", e)

        # ponytail: payload has no category field — category text lives inside `text` — so no filter,
        # similarity over 71 points only; add a real category payload field when the collection grows
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
            return f"search failed: {type(e).__name__}: {e}"

        if not points:
            logger.info("item hybrid_search category=%r query=%r -> no results", category, q)
            return "no results"
        lines = []
        for p in points:
            payload = getattr(p, "payload", {}) or {}
            name = extract_item_name(payload.get("text") or "")
            text = (payload.get("text") or "")[:300]
            lines.append(f"{name}: {text}".strip())
        result = "\n".join(lines)
        logger.info(
            "item hybrid_search category=%r query=%r -> %s hits, agent receives: %s",
            category, q, len(points), result[:500],
        )
        return result

    return hybrid_search