import logging
import threading

from sentence_transformers import CrossEncoder

from lib.core.config import settings
from agents.intelligence.subagents.search.state import SearchState

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


def _cross_encoder_scores(query: str, hits: list[dict]) -> list[float]:
    # ponytail: batch predict, O(n) single call; no per-hit LLM loop
    pairs = [(query, (h.get("text") or "")[:4000]) for h in hits]
    scores = _get_model().predict(pairs, batch_size=32, convert_to_numpy=True, show_progress_bar=False)
    # scores are raw logits (~ -10 to 10), higher = more relevant
    return [float(s) for s in scores]


def _jev_scores(query: str, hits: list[dict]) -> list[float]:
    """One JEV call per search. +confidence for a confident 'relevant', else -confidence."""
    from typesafe_sdk import Choice

    from lib.core.jev import get_jev

    keys = [f"c{i}" for i in range(len(hits))]
    # ponytail: 1500 chars x 20 hits keeps the state ~8k tokens; raise if chunks get truncated mid-answer
    chunks = {k: (h.get("text") or "")[:1500] for k, h in zip(keys, hits)}
    choice = lambda k: Choice(  # noqa: E731
        instructions=(
            f"Decide if tender document chunk {k} in state.chunks contains information that helps answer "
            "state.query. A chunk that only shares keywords but does not address the query is irrelevant."
        ),
        criteria={
            "relevant": "the chunk contains information that answers or directly supports the query",
            "irrelevant": "the chunk does not help answer the query",
        },
    )
    result = get_jev(settings.typesafe_api_key, settings.typesafe_model).system_one(
        state={"query": query, "chunks": chunks},
        questions={k: choice(k) for k in keys},
    )
    scores = []
    for k in keys:
        answer = result.choices.get(k)
        confidence = float(getattr(answer, "confidence", None) or 0.0)
        relevant = getattr(answer, "choice", None) == "relevant" and confidence >= _JEV_MIN_CONFIDENCE
        scores.append(confidence if relevant else -confidence)
    return scores


_SCORERS = {"cross_encoder": (_cross_encoder_scores, "cross-encoder"), "jev": (_jev_scores, "jev")}
_JEV_MIN_CONFIDENCE = 0.5


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
        backend = settings.rerank_backend
        if backend not in _SCORERS:
            raise ValueError(f"unknown RERANK_BACKEND={backend!r}, expected one of {sorted(_SCORERS)}")
        scorer, reason = _SCORERS[backend]
        scores = scorer(query, hits)
        reranked: list[dict] = []
        for h, score in zip(hits, scores):
            # ponytail: threshold 0 — cross-encoder logit sigmoid 0.5 boundary, jev sign = relevant;
            # upgrade to calibrated threshold after eval
            is_valid = score > 0
            reranked.append({**h, "rerank_score": score, "is_valid": is_valid, "reason": reason})

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


if __name__ == "__main__":
    import sys
    import types

    sys.modules["typesafe_sdk"] = types.SimpleNamespace(Choice=lambda **kw: kw)
    import lib.core.jev as jev

    answers = {
        "c0": types.SimpleNamespace(choice="irrelevant", confidence=0.9),
        "c1": types.SimpleNamespace(choice="relevant", confidence=0.7),
        "c2": types.SimpleNamespace(choice="relevant", confidence=0.95),
        "c3": types.SimpleNamespace(choice="relevant", confidence=0.3),  # too unsure
    }
    calls = []
    jev.get_jev = lambda *a: types.SimpleNamespace(
        system_one=lambda **kw: calls.append(kw) or types.SimpleNamespace(choices=answers)
    )
    settings.rerank_backend = "jev"
    hits = [{"text": f"t{i}", "score": i} for i in range(4)]
    out = rerank({"query": "q", "hits": hits})
    assert out["status"] == "reranked", out
    assert [v["text"] for v in out["valid"]] == ["t2", "t1"], out["valid"]
    assert all(v["reason"] == "jev" for v in out["valid"])
    assert len(calls) == 1 and set(calls[0]["questions"]) == {"c0", "c1", "c2", "c3"}

    # jev down -> qdrant fallback, job not crashed
    jev.get_jev = lambda *a: (_ for _ in ()).throw(RuntimeError("down"))
    assert rerank({"query": "q", "hits": hits})["status"] == "rerank_fallback"

    # typo in env -> fallback, not silent cross-encoder
    settings.rerank_backend = "jevv"
    assert "RERANK_BACKEND" in rerank({"query": "q", "hits": hits})["error"]
    print("rerank ok")
