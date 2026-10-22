import logging
from typing import Any

from lib.core.config import settings
from lib.core.jev import DEFAULT_MODEL, get_jev

logger = logging.getLogger(__name__)

CHOICES = ("identical", "different", "needs_review")
# below this JEV is guessing, and a certificate verdict is high-stakes: never guess
MIN_CONFIDENCE = 0.5

def _evidence(state: dict[str, Any], duplicates: list, unresolved: list) -> dict[str, Any]:
    """Filtered structured evidence for JEV. Never raw page text: state is text-only and capped ~32k tokens."""
    return {
        "job_id": state.get("job_id"),
        "counts": {
            "duplicates": len(duplicates),
            "unresolved": len(unresolved),
            "pages": state.get("page_count") or len(state.get("pages") or []),
        },
        # similarities and uncertainty kinds are already numbers/labels, so JEV never does counting or date math
        "similarities": [u.get("similarity") for u in unresolved if isinstance(u, dict) and u.get("similarity") is not None],
        "unresolved_kinds": sorted({str(u.get("kind") or u.get("type") or "unknown") for u in unresolved}),
        "unresolved": unresolved,
        "duplicate_groups": duplicates,
    }


def _ask_jev(state: dict[str, Any], duplicates: list, unresolved: list):
    """Returns (decision, reliability_score, model). Raises on any JEV failure."""
    from typesafe_sdk import Choice, Score

    client = get_jev(settings.typesafe_api_key, settings.typesafe_model)
    result = client.system_one(
        state=_evidence(state, duplicates, unresolved),
        questions={
            "verdict": Choice(
                instructions=(
                    "Two documents are checked as performance certificates of the same tender. "
                    "Every count, similarity and date in the state is already computed and verified by code; "
                    "never recompute or contradict it. Unresolved items are places the pipeline could not "
                    "confirm or refute; duplicate groups are pages that repeat the same content. "
                    "Answer 'identical' only when nothing is unresolved. "
                    "Answer 'different' only for a real, verified difference. "
                    "Answer 'needs_review' whenever the evidence is inconclusive or contradictory."
                ),
                criteria={
                    "identical": "no meaningful difference between the documents and nothing unresolved",
                    "different": "a verified meaningful difference exists",
                    "needs_review": "evidence is inconclusive, uncertain, or contradictory",
                },
            ),
            "extraction_reliability": Score(
                instructions="How reliable is the extracted evidence: are the pages clean, complete and legible?",
                criteria=["Unusable or unreadable", "Partially reliable", "Clean and complete"],
            ),
        },
    )

    answer = result.choices["verdict"]
    decision = str(answer.choice or "").strip()
    confidence = float(answer.confidence or 0.0)
    logger.info("jev ref=%s choice=%s confidence=%.3f", state.get("job_id"), decision, confidence)

    if decision not in CHOICES:
        logger.warning("jev returned unknown choice=%r, forcing needs_review", decision)
        decision = "needs_review"
    if confidence < MIN_CONFIDENCE:
        decision = "needs_review"

    score = None
    try:
        score = float(result.scores["extraction_reliability"].score)
    except Exception:  # a missing score is not worth failing a decided verdict
        logger.warning("jev ref=%s no extraction_reliability score", state.get("job_id"))

    model = settings.typesafe_model or DEFAULT_MODEL
    return decision, score, model


def decide(state: dict[str, Any]) -> dict[str, Any]:
    ref = (state.get("job_id") or "").strip()
    diffs = state.get("diffs") or []
    unresolved = state.get("unresolved") or []
    duplicates = state.get("duplicates") or []

    def out(decision: str, notes: str, model: str | None = None, error: str | None = None) -> dict[str, Any]:
        return {
            "decision": decision,
            "report": {
                "decision": decision,
                "differences": diffs,
                "unresolved": unresolved,
                "duplicates": duplicates,
                "details": state.get("details") or [],
                "notes": notes,
                "model": model,
            },
            "status": "failed" if error else "decided",
            "error": error,
        }

    # verified evidence wins: never spend a JEV call on a difference code already proved
    if diffs:
        logger.info("ref=%s decision=different from %s verified diff(s)", ref, len(diffs))
        return out("different", f"{len(diffs)} verified difference(s) found; JEV not consulted")

    if unresolved:
        try:
            decision, score, model = _ask_jev(state, duplicates, unresolved)
        except Exception as e:
            err = f"jev failed: {type(e).__name__}: {e}"
            logger.error("decide ref=%s %s", ref, err, exc_info=True)
            return out("needs_review", f"{len(unresolved)} unresolved item(s) and JEV unavailable", error=err)
        notes = f"{len(unresolved)} unresolved item(s) referred to JEV"
        if score is not None:
            notes += f"; extraction reliability {score:.2f}"
        logger.info("ref=%s decision=%s (jev)", ref, decision)
        return out(decision, notes, model=model)

    logger.info("ref=%s decision=identical, nothing unresolved", ref)
    return out("identical", "no verified difference and nothing unresolved")


# shortcut: no image/vision pass here, JEV is text-only. Visual escalation (rendered page
# comparison for scans) is handled elsewhere and is not implemented yet.
if __name__ == "__main__":
    import sys
    import types

    # diffs win without JEV
    r = decide({"job_id": "R1", "diffs": [{"field": "amount", "a": 1, "b": 2}]})
    assert r["decision"] == "different" and r["report"]["model"] is None and r["status"] == "decided", r
    # nothing to worry about -> identical, still no JEV; duplicates travel in the report (webhook body)
    r = decide({"job_id": "R2", "duplicates": [{"certificate_id": "C1", "sha256": "ab", "duplicate_of": ["C2"]}]})
    assert r["decision"] == "identical" and r["report"]["model"] is None, r
    assert r["report"]["duplicates"] == [{"certificate_id": "C1", "sha256": "ab", "duplicate_of": ["C2"]}], r

    # unresolved -> JEV decides; stub the SDK so this check runs offline
    fake = types.SimpleNamespace(
        choices={"verdict": types.SimpleNamespace(choice="identical", confidence=0.97)},
        scores={"extraction_reliability": types.SimpleNamespace(score=0.9)},
    )
    decide.__globals__["get_jev"] = lambda *a: types.SimpleNamespace(system_one=lambda **kw: fake)
    sys.modules["typesafe_sdk"] = types.SimpleNamespace(Choice=lambda **kw: kw, Score=lambda **kw: kw)
    r = decide({"job_id": "R3", "unresolved": [{"kind": "amount", "similarity": 0.81}]})
    assert r["decision"] == "identical" and r["report"]["model"] and r["status"] == "decided", r

    # low confidence -> forced review
    fake.choices["verdict"].confidence = 0.4
    r = decide({"job_id": "R4", "unresolved": [{"kind": "date"}]})
    assert r["decision"] == "needs_review" and r["status"] == "decided", r

    # JEV blows up -> needs_review, job not crashed
    def boom(**kw):
        raise RuntimeError("no api key")

    decide.__globals__["get_jev"] = lambda *a: types.SimpleNamespace(system_one=boom)
    r = decide({"job_id": "R5", "unresolved": [{"kind": "page"}]})
    assert r["decision"] == "needs_review" and r["status"] == "failed" and "RuntimeError" in r["error"], r
    print("decide ok")
