import logging

from langchain_openai import OpenAIEmbeddings
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, Prefetch, SparseVector

from core.config import settings
from intelligence.subagents.search.state import SearchState
from vector.qdrant import ensure_collection, qdrant

try:
    from fastembed import SparseTextEmbedding
except ImportError:
    SparseTextEmbedding = None  # type: ignore

logger = logging.getLogger(__name__)

_dense_embedder = None
_sparse_embedder = None


def _get_dense():
    global _dense_embedder
    if _dense_embedder is not None:
        return _dense_embedder
    api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
    if not api_key:
        raise ValueError("OPENAI_API_KEY missing")
    _dense_embedder = OpenAIEmbeddings(model=settings.embedding_model, api_key=api_key)
    return _dense_embedder


def _get_sparse():
    global _sparse_embedder
    if _sparse_embedder is not None:
        return _sparse_embedder
    if SparseTextEmbedding is None:
        logger.warning("fastembed not installed, dense-only fallback")
        _sparse_embedder = None
        return _sparse_embedder
    try:
        _sparse_embedder = SparseTextEmbedding(model_name="Qdrant/bm25")
    except Exception as e:
        logger.warning("sparse BM25 init failed, dense-only fallback: %s", e)
        _sparse_embedder = None
    return _sparse_embedder


def hybrid_search(state: SearchState) -> dict:
    query = (state.get("query") or "").strip()
    keywords = state.get("keywords") or []
    reference_no = (state.get("reference_no") or "").strip() or None

    if not query:
        err = "query is required"
        logger.error(err)
        return {"hits": [], "status": "failed", "error": err}

    # embed query
    try:
        dense = _get_dense().embed_query(query)
    except Exception as e:
        err = f"dense embed failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"hits": [], "status": "failed", "error": err}

    # sparse from query + keywords — ponytail: single text, no keyword-weighted boost until recall gap
    sparse_vec = None
    try:
        sparse_emb = _get_sparse()
        if sparse_emb is not None:
            text = query + (" " + " ".join(keywords) if keywords else "")
            raw = list(sparse_emb.embed([text]))[0]
            indices = raw.indices.tolist() if hasattr(raw.indices, "tolist") else list(raw.indices)
            values = raw.values.tolist() if hasattr(raw.values, "tolist") else list(raw.values)
            if indices and values:
                sparse_vec = SparseVector(indices=indices, values=values)
    except Exception as e:
        logger.warning("sparse embed failed, dense-only: %s", e)

    # optional filter by reference_no
    q_filter = None
    if reference_no:
        q_filter = Filter(must=[FieldCondition(key="reference_no", match=MatchValue(value=reference_no))])

    try:
        coll = ensure_collection()
        # ponytail: dense-only query_points until hybrid RRF proves need; sparse passed when available via qdrant hybrid
        # qdrant_client >=1.9 supports query_points with sparse; fallback to dense search
        hits = []
        try:
            # try hybrid via query with both vectors (qdrant hybrid)
            if sparse_vec is not None:
                # use query_points with prefetch fusion — ponytail: simple single query, not RRF multi-prefetch
                # fallback attempt: if hybrid api differs, exception triggers dense fallback
                res = qdrant.query_points(
                    collection_name=coll,
                    prefetch=[
                        Prefetch(query=dense, using="dense", limit=20, filter=q_filter),
                        Prefetch(query=sparse_vec, using="sparse", limit=20, filter=q_filter),
                    ],
                    query=dense,
                    using="dense",
                    limit=20,
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
                limit=20,
                with_payload=True,
                query_filter=q_filter,
            )
            points = res.points if hasattr(res, "points") else []

        # normalize points -> hits
        for p in points:
            payload = getattr(p, "payload", {}) or {}
            hits.append(
                {
                    "id": str(getattr(p, "id", "")),
                    "score": float(getattr(p, "score", 0) or 0),
                    "text": payload.get("text") or "",
                    "payload": payload,
                }
            )

        logger.info("hybrid_search query=%r keywords=%s ref=%s hits=%s", query[:80], keywords, reference_no, len(hits))
        return {"hits": hits, "status": "searched", "error": None}
    except Exception as e:
        err = f"qdrant query failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"hits": [], "status": "failed", "error": err}
