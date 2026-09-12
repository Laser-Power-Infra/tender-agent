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

# ponytail: hits handed to one document's synthesis. execute_search takes _HITS_PER_DOC=2 of these.
_MAX_VALID = 5


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
        # ponytail: the weak-relevance fallback (top[:3] when the best logit merely cleared -1) is
        # gone. Every synthesis prompt says "ground every value ONLY in the provided search_results",
        # and that fallback handed the model chunks this reranker had just judged irrelevant.
        # synthesize renders an empty document as "(no chunks retrieved)", which is the honest answer.
        dropped = len(reranked) - len(valid)
        valid = valid[:_MAX_VALID]
        logger.info(
            "rerank done query=%r hits=%s valid=%s below_threshold=%s capped=%s",
            query[:80], len(hits), len(valid), dropped, max(0, len(reranked) - dropped - _MAX_VALID),
        )
        return {"reranked": reranked, "valid": valid, "status": "reranked" if valid else "no_valid", "error": None}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("rerank failed query=%r error=%s", query[:80], err, exc_info=True)
        # ponytail: model down, fall back to qdrant order. Carries the same keys as the success path
        # — an item without rerank_score was silently filtered out downstream by execute_search and
        # cost every document half its hits. reason is what tells the caller these are not reranked.
        ordered = sorted(hits, key=lambda x: x.get("score") or 0, reverse=True)[:_MAX_VALID]
        valid = [{**h, "rerank_score": None, "is_valid": True, "reason": "qdrant-score-fallback"} for h in ordered]
        logger.warning("rerank fallback to qdrant order query=%r hits=%s kept=%s", query[:80], len(hits), len(valid))
        return {"reranked": valid, "valid": valid, "status": "rerank_fallback", "error": err}
