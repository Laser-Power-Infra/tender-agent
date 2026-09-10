import logging

from langchain_openai import ChatOpenAI

from core.config import settings
from intelligence.subagents.specialized.prompts import AGENT_PROMPTS, SPECIALIZED_PLAN_MODEL
from intelligence.subagents.specialized.query_schemas import AGENT_QUERY_MODELS, DEFAULT_QUERY_MODEL
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
    # ponytail: model constant from prompts, change one place
    _llm = ChatOpenAI(model=SPECIALIZED_PLAN_MODEL, api_key=api_key, temperature=0)
    return _llm


def generate_queries(state: SpecializedState) -> dict:
    reference_no = (state.get("reference_no") or "").strip()
    task = state.get("task") or {}
    agent = (state.get("agent") or task.get("agent") or "").strip()
    system_prompt = (state.get("system_prompt") or AGENT_PROMPTS.get(agent) or "").strip()

    if not reference_no:
        err = "reference_no required"
        logger.error(err)
        return {"query_pairs": [], "status": "failed", "error": err}
    if not system_prompt:
        system_prompt = "You are tender research planner. Generate 5-10 query+keyword pairs for the task."

    task_desc = task.get("description") or task.get("task_id") or agent
    # ponytail: per-agent query model, agent type -> proper schema
    QueryModel = AGENT_QUERY_MODELS.get(agent, DEFAULT_QUERY_MODEL)
    try:
        llm = _get_llm()
        structured = llm.with_structured_output(QueryModel)
        result = structured.invoke(
            [
                ("system", system_prompt),
                ("human", f"reference_no: {reference_no}\ntask: {task_desc}"),
            ]
        )
        items = [it.model_dump() for it in result.items] if result and getattr(result, "items", None) else []
        if not items:
            logger.warning("generate_queries empty agent=%s ref=%s", agent, reference_no)
            return {"query_pairs": [], "status": "partial", "error": "empty plan"}
        logger.info("generate_queries agent=%s ref=%s items=%s", agent, reference_no, len(items))
        return {"query_pairs": items, "status": "planned", "error": None}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("generate_queries failed agent=%s ref=%s error=%s", agent, reference_no, err, exc_info=True)
        return {"query_pairs": [], "status": "failed", "error": err}
