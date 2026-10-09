import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.config import settings
from database.connection import get_session_context
from database.models import AIRelevance
from intelligence.llm import get_llm
from relevance.nodes.feedback import brief_of
from relevance.prompts import DEFAULT, DEFAULT_CATEGORY, FEEDBACK_RULE, PROMPTS

logger = logging.getLogger(__name__)


class RelevanceVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")

    valid: bool = Field(description="whether the brief is a valid tender fit for the company")
    reason: str = Field(description="why the brief is or is not valid; name the human feedback when it decided the verdict")


def _format_hit(h: dict) -> str:
    payload = h.get("payload") or {}
    score = float(h.get("score") or 0)
    if h.get("same_tender"):
        tag = "[SAME TENDER]"
    elif score >= settings.relevance_override_score:
        tag = f"[NEAR-DUPLICATE TENDER, score {score:.2f}]"
    else:
        tag = f"[similar tender, score {score:.2f}]"
    if payload.get("brief"):  # new-format point: brief and human words stored apart
        return f"{tag}\nbrief: {payload['brief']}\nhuman feedback: {payload.get('feedback') or ''}"
    return f"{tag}\n{h.get('text') or ''}"  # old point: raw k: v chunk


def analyze(state: dict[str, Any]) -> dict[str, Any]:
    ref = (state.get("reference_no") or "").strip()
    extra = state.get("extra") or {}
    brief = brief_of(extra)
    itemcategory = (extra.get("itemcategory") or extra.get("itemCategory") or "").strip()
    hits = state.get("hits") or []

    if not brief:
        err = "tenderbrief missing in extra"
        logger.error("%s ref=%s", err, ref)
        return {"verdict": {}, "status": "failed", "error": err}

    feedback_text = "\n\n".join(_format_hit(h) for h in hits if h.get("text")) or "(no human feedback found)"
    logger.info(
        "analyze ref=%s feedback_hits=%s feedback_text=%r",
        ref, len(hits), feedback_text[:500],
    )

    tenderamount = str(state.get("tender_amount") or "").strip()
    company = str(state.get("company") or "").lower()
    category = str(state.get("category") or extra.get("category") or DEFAULT_CATEGORY.get(company) or "").strip().lower()
    prompt_key = f"{company}_{category}"
    system_prompt = (PROMPTS.get(prompt_key) or "").strip()
    if not system_prompt:
        logger.warning("no prompt for key=%s, falling back to default", prompt_key)
        system_prompt = DEFAULT
    system_prompt = f"{system_prompt}\n\n{FEEDBACK_RULE}"

    try:
        llm = get_llm()
        structured = llm.with_structured_output(RelevanceVerdict)
        result = structured.invoke(
            [
                ("system", system_prompt),
                ("human", f"item category: {itemcategory or 'unspecified'}\ntender amount: {tenderamount or 'unspecified'}\nbrief: {brief}\n\nhuman feedback:\n{feedback_text}"),
            ]
        )
        if not result:
            raise ValueError("empty structured output")
        verdict = {"valid": result.valid, "reason": result.reason, "category": category}
        logger.info("analyze ref=%s valid=%s", ref, result.valid)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("analyze failed ref=%s error=%s", ref, err, exc_info=True)
        return {"verdict": {}, "status": "failed", "error": err}

    # persist — ponytail: row stores verdict json + reason; a db failure fails the job (analysis is the point)
    try:
        with get_session_context() as session:
            session.add(
                AIRelevance(
                    reference_no=ref,
                    company=state.get("company"),
                    brief=brief,
                    ai_answer=json.dumps(verdict),
                    ai_reason=result.reason,
                )
            )
            session.commit()
        logger.info("ai_relevance row saved ref=%s", ref)
    except Exception as e:
        err = f"ai_relevance db save failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"verdict": verdict, "status": "failed", "error": err}

    return {"verdict": verdict, "status": "analyzed", "error": None}