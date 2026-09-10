import logging
import threading

from sentence_transformers import CrossEncoder

from core.config import settings
from intelligence.subagents.search.state import SearchState

logger = logging.getLogger(__name__)

# ponytail: singleton CrossEncoder, lazy load on first predict; cpu default via settings.rerank_device.
# locked because searches now run in parallel — an unlocked race loads the model twice.
_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            # ponytail: model/device from settings (env RERANK_MODEL/RERANK_DEVICE), no hardcode in node
            model_name = settings.rerank_model
            device = settings.rerank_device
            if device == "cpu":
                # ponytail: ~32 predict() calls run concurrently, each otherwise sizing its intra-op
                # pool to the core count — pure oversubscription thrash. Identical scores, less thrash.
                # Process-local, so the ingestion container's docling threads are untouched.
                import torch

                torch.set_num_threads(1)
            _model = CrossEncoder(model_name, device=device, max_length=512)
            logger.info("CrossEncoder loaded model=%s device=%s", model_name, device)
    return _model


def rerank(state: SearchState) -> dict:
    query = (state.get("query") or "").strip()
    hits: list[dict] = state.get("hits") or []

    if not hits:
        logger.info("rerank skip, no hits query=%r", query[:80])
        return {"reranked": [], "valid": [], "status": "no_hits", "error": None}

    if not query:
        err = "query is required for rerank"
        logger.error(err)
        return {"reranked": [], "valid": [], "status": "failed", "error": err}

    try:
        model = _get_model()
        # ponytail: batch predict, O(n) single call; no per-hit LLM loop
        pairs = [(query, (h.get("text") or "")[:4000]) for h in hits]
        scores = model.predict(pairs, batch_size=32, convert_to_numpy=True, show_progress_bar=False)
        # scores are raw logits (~ -10 to 10), higher = more relevant
        reranked: list[dict] = []
        for h, s in zip(hits, scores):
            score = float(s)
            # ponytail: threshold 0 on raw logits (sigmoid 0.5 boundary); upgrade to calibrated threshold after eval
            is_valid = score > 0
            reranked.append({**h, "rerank_score": score, "is_valid": is_valid, "reason": "cross-encoder"})

        valid = [r for r in reranked if r.get("is_valid")]
        valid.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        valid = valid[:5]

        if not valid:
            # fallback: take top if max score > -1 (weak relevance)
            top = sorted(reranked, key=lambda x: x.get("rerank_score", 0), reverse=True)
            if top and top[0].get("rerank_score", 0) > -1:
                valid = top[:3]
                logger.info("rerank fallback weak threshold query=%r valid=%s", query[:80], len(valid))

        logger.info("rerank done query=%r hits=%s valid=%s", query[:80], len(hits), len(valid))
        return {"reranked": reranked, "valid": valid, "status": "reranked" if valid else "no_valid", "error": None}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("rerank failed query=%r error=%s", query[:80], err, exc_info=True)
        # ponytail: fallback to qdrant score top5 on model failure
        valid = sorted(hits, key=lambda x: x.get("score", 0), reverse=True)[:5]
        return {"reranked": hits, "valid": valid, "status": "rerank_fallback", "error": err}
