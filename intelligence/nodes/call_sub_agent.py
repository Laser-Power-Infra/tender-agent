import logging

from intelligence.state import IntelligenceState
from intelligence.subagents.specialized.graph import get_specialized_graph
from intelligence.subagents.specialized.prompts import AGENT_PROMPTS

logger = logging.getLogger(__name__)

def call_sub_agent(state: IntelligenceState) -> dict:
    task = state.get("current_task")
    reference_no = (state.get("reference_no") or "").strip()
    parsed_request = state.get("parsed_request") or {}

    if not task:
        err = "current_task missing, skip call"
        logger.error(err)
        # ponytail: agent_result transient not in TypedDict yet, stored dynamically; declare in state.py if strict typing needed
        return {"agent_result": {"task_id": None, "agent": None, "status": "failed", "result": {}, "sources": [], "error": err}}

    task_id = task.get("task_id")
    agent = (task.get("agent") or "").strip()
    if not agent:
        err = "agent missing in current_task"
        logger.error("%s task_id=%s", err, task_id)
        return {"agent_result": {"task_id": task_id, "agent": agent, "status": "failed", "result": {}, "sources": [], "error": err}}

    # ponytail: no user_query passed, not mandatory; task.description drives query gen
    payload = {
        "reference_no": reference_no,
        "parsed_request": parsed_request,
        "task": task,
        "agent": agent,
        "system_prompt": AGENT_PROMPTS.get(agent, ""),
    }

    try:
        graph = get_specialized_graph()
        out = graph.invoke(payload)
        result = out.get("result") or {}
        sources = out.get("sources") or []
        status = out.get("status") or "success"
        error = out.get("error")
        # envelope per spec §13
        envelope = {
            "task_id": task_id,
            "agent": agent,
            "status": status,
            "result": result,
            "sources": sources,
            "error": error,
        }
        logger.info("call_sub_agent done task_id=%s agent=%s status=%s sources=%s", task_id, agent, status, len(sources))
        return {"agent_result": envelope}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("call_sub_agent failed task_id=%s agent=%s error=%s", task_id, agent, err, exc_info=True)
        return {"agent_result": {"task_id": task_id, "agent": agent, "status": "failed", "result": {}, "sources": [], "error": err}}
