import json
import logging

from pydantic import BaseModel, Field

from intelligence.llm import get_llm
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
    sections: dict = Field(description="keyed by task, each holding that agent's result")
    evidence: list[dict] = Field(default_factory=list, description="key evidence items with source")


# per-agent guard, only trips on a pathological result — the raw chunk text is already gone
_MAX_AGENT_CHARS = 6000


def _drop_unclear(result):
    """Replace a document section's "Unclear" rows with a count.

    ponytail: a 25-document section typically returns mostly "Unclear". Across ~47 sections that is
    ~280k chars of nothing in one prompt. The final report only needs what the tender actually asks
    for; the complete per-section detail stays in agent_results and the checkpointer.
    """
    rows = (result or {}).get("results")
    if not isinstance(rows, list):
        return result
    kept = [r for r in rows if (r or {}).get("required") != "Unclear"]
    return {"results": kept, "unclear_count": len(rows) - len(kept)}


def _agent_blocks(agent_results: dict) -> str:
    """One labeled JSON block per task.

    Drops `sources`: it is raw Qdrant chunk text, tens of thousands of chars across five agents,
    and the spec says synthesis sees structured agent results only. Capping each block separately
    means a long result truncates itself, never the agents that follow it.
    """
    blocks = []
    for task_id, envelope in agent_results.items():
        envelope = envelope or {}
        trimmed = {k: envelope.get(k) for k in ("agent", "status", "result", "error") if envelope.get(k) is not None}
        if "result" in trimmed:
            trimmed["result"] = _drop_unclear(trimmed["result"])
        body = json.dumps(trimmed, ensure_ascii=False)
        if len(body) > _MAX_AGENT_CHARS:
            logger.warning("synthesis input truncated task_id=%s len=%s cap=%s", task_id, len(body), _MAX_AGENT_CHARS)
            body = body[:_MAX_AGENT_CHARS] + " ...[truncated]"
        blocks.append(f"### {task_id}\n{body}")
    return "\n\n".join(blocks)


def synthesize_final_result(state: IntelligenceState) -> dict:
    reference_no = (state.get("reference_no") or "").strip()
    agent_results = state.get("agent_results") or {}
    parsed_request = state.get("parsed_request") or {}

    if not agent_results:
        err = "agent_results empty, nothing to synthesize"
        logger.warning("%s ref=%s", err, reference_no)
        return {"final_response": {"tender_id": reference_no, "summary": err, "sections": {}, "evidence": []}, "errors": [{"node": "synthesize_final_result", "error": err}]}

    try:
        llm = get_llm()
        structured = llm.with_structured_output(FinalResponse)
        human = (
            f"reference_no: {reference_no}\n"
            f"parsed_request: {json.dumps(parsed_request, ensure_ascii=False)}\n"
            f"agent_results:\n{_agent_blocks(agent_results)}"
        )
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
