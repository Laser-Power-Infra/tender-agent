import logging

from langchain_openai import ChatOpenAI

from core.config import settings
from intelligence.subagents.specialized.prompts import SPECIALIZED_SYNTHESIS_MODEL, SYNTHESIS_PROMPT
from intelligence.subagents.specialized.schemas import AGENT_OUTPUT_MODELS, SynthesisResult
from intelligence.subagents.specialized.state import SpecializedState

logger = logging.getLogger(__name__)


_llm = None


def _get_llm():
    global _llm
    if _llm is not None:
        return _llm
    api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
    if not api_key:
        raise ValueError("OPENAI_API_KEY missing")
    _llm = ChatOpenAI(model=SPECIALIZED_SYNTHESIS_MODEL, api_key=api_key, temperature=0)
    return _llm


def synthesize(state: SpecializedState) -> dict:
    task = state.get("task") or {}
    agent = (state.get("agent") or task.get("agent") or "").strip()
    search_results: list[dict] = state.get("search_results") or []
    reference_no = (state.get("reference_no") or "").strip()

    if not search_results:
        logger.info("synthesize no results agent=%s ref=%s", agent, reference_no)
        return {
            "result": {"summary": "No relevant context found", "findings": [], "evidence": [], "documents": []},
            "status": "no_results",
            "error": None,
        }

    # build context from hits — ponytail: 21 hits *800 chars ~8000, per-pair 3 accumulation
    chunks = []
    for r in search_results[:21]:
        hit = r.get("hit") or {}
        txt = (hit.get("text") or "").strip()
        if txt:
            chunks.append(txt[:800])
    context = "\n\n---\n\n".join(chunks)[:8000]
    task_desc = task.get("description") or task.get("task_id") or agent
    # ponytail: per-agent synthesis prompt dict, agent type -> proper prompt
    if isinstance(SYNTHESIS_PROMPT, dict):
        raw_prompt = SYNTHESIS_PROMPT.get(agent) or SYNTHESIS_PROMPT.get("company_document_finder") or ""
    else:
        raw_prompt = str(SYNTHESIS_PROMPT or "")
    if not raw_prompt:
        raw_prompt = "You are {agent} synthesis. Combine context for task: {task_description}."
    if "{agent}" in raw_prompt or "{task_description}" in raw_prompt:
        try:
            sys_prompt = raw_prompt.format(agent=agent or "specialized", task_description=task_desc)
        except Exception:
            sys_prompt = raw_prompt
    else:
        sys_prompt = raw_prompt

    # ponytail: per-agent output model, agent type -> proper schema
    OutputModel = AGENT_OUTPUT_MODELS.get(agent, SynthesisResult)
    try:
        llm = _get_llm()
        structured = llm.with_structured_output(OutputModel)
        out = structured.invoke(
            [
                ("system", sys_prompt),
                ("human", f"reference_no: {reference_no}\ncontext:\n{context}"),
            ]
        )
        result = out.model_dump() if out else {}
        logger.info("synthesize done agent=%s model=%s ref=%s", agent, OutputModel.__name__, reference_no)
        return {"result": result, "status": "success", "error": None}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("synthesize failed agent=%s ref=%s error=%s", agent, reference_no, err, exc_info=True)
        # ponytail: fallback aggregate without LLM
        fallback = {"summary": chunks[0][:500] if chunks else "", "findings": chunks[:3], "evidence": chunks[:3], "documents": []}
        return {"result": fallback, "status": "fallback", "error": err}
