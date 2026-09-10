import json
import logging

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from core.config import settings
from intelligence.state import IntelligenceState

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """You are the final synthesis component of a tender research system.

You have received structured results from multiple specialized research agents.

Your job is to combine those results into one final structured response.

Rules:
- Use only the information provided by the agent results.
- Do not perform new research.
- Do not invent missing information.
- Preserve important evidence and details.
- Remove duplicate information.
- Clearly separate information belonging to different sections.
- If agents disagree, preserve the conflict or identify the discrepancy rather than inventing a resolution.
- Follow the required output schema exactly."""

class FinalResponse(BaseModel):
    tender_id: str = Field(description="tender reference number")
    summary: str = Field(description="2-3 sentence summary of findings")
    sections: dict = Field(description="keyed by agent e.g. company_document_finder, reverse_auction with their result")
    evidence: list[dict] = Field(default_factory=list, description="key evidence items with source")

# ponytail: single LLM instance
_llm = None

def _get_llm():
    global _llm
    if _llm is not None:
        return _llm
    api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
    if not api_key:
        raise ValueError("OPENAI_API_KEY missing (set in .env)")
    # ponytail: gpt-4o-mini cheapest, upgrade when quality needs prove
    _llm = ChatOpenAI(model="gpt-4o-mini", api_key=api_key, temperature=0)
    return _llm

def synthesize_final_result(state: IntelligenceState) -> dict:
    reference_no = (state.get("reference_no") or "").strip()
    agent_results = state.get("agent_results") or {}
    parsed_request = state.get("parsed_request") or {}

    if not agent_results:
        err = "agent_results empty, nothing to synthesize"
        logger.warning("%s ref=%s", err, reference_no)
        return {"final_response": {"tender_id": reference_no, "summary": err, "sections": {}, "evidence": []}, "errors": [{"node": "synthesize_final_result", "error": err}]}

    try:
        llm = _get_llm()
        structured = llm.with_structured_output(FinalResponse)
        human = f"reference_no: {reference_no}\nparsed_request: {json.dumps(parsed_request, ensure_ascii=False)}\nagent_results: {json.dumps(agent_results, ensure_ascii=False)[:12000]}"
        result: FinalResponse = structured.invoke([("system", SYNTHESIS_SYSTEM_PROMPT), ("human", human)])
        final = result.model_dump() if result else {}
        # ensure tender_id filled
        if not (final.get("tender_id") or "").strip() and reference_no:
            final["tender_id"] = reference_no
        logger.info("synthesize_final_result done ref=%s sections=%s", reference_no, len(final.get("sections") or {}))
        return {"final_response": final}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("synthesize_final_result failed ref=%s error=%s", reference_no, err, exc_info=True)
        # ponytail: fallback without LLM, passthrough agent_results
        fallback = {"tender_id": reference_no, "summary": f"fallback synthesis due to {err}", "sections": agent_results, "evidence": []}
        return {"final_response": fallback, "errors": [{"node": "synthesize_final_result", "error": err}]}
