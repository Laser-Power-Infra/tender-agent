import logging

from intelligence.llm import get_llm
from intelligence.subagents.specialized.document_agents import STATIC_QUERIES
from intelligence.subagents.specialized.prompts import AGENT_PROMPTS
from intelligence.subagents.specialized.query_schemas import QueryPairs
from intelligence.subagents.specialized.state import SpecializedState

logger = logging.getLogger(__name__)


def generate_queries(state: SpecializedState) -> dict:
    reference_no = (state.get("reference_no") or "").strip()
    task = state.get("task") or {}
    agent = (state.get("agent") or task.get("agent") or "").strip()
    system_prompt = (AGENT_PROMPTS.get(agent) or "").strip()

    if not reference_no:
        err = "reference_no required"
        logger.error(err)
        return {"query_pairs": [], "status": "failed", "error": err}

    static = STATIC_QUERIES.get(agent)
    if static:
        logger.info("generate_queries static agent=%s ref=%s items=%s", agent, reference_no, len(static))
        return {"query_pairs": [dict(item) for item in static], "status": "planned", "error": None}

    if not system_prompt:
        system_prompt = "You are tender research planner. Generate 5-10 query+keyword pairs for the task."

    task_desc = task.get("description") or task.get("task_id") or agent
    try:
        llm = get_llm()
        structured = llm.with_structured_output(QueryPairs)
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
