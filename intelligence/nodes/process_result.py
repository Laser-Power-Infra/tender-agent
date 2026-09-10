import logging

from intelligence.state import IntelligenceState

logger = logging.getLogger(__name__)

def process_result(state: IntelligenceState) -> dict:
    task = state.get("current_task")
    res = state.get("agent_result")
    checklist = state.get("checklist") or []
    agent_results = dict(state.get("agent_results") or {})
    errors = list(state.get("errors") or [])

    if not task:
        err = "current_task missing in process_result"
        logger.error(err)
        errors.append({"node": "process_result", "error": err})
        return {"errors": errors, "agent_result": None}

    if not res:
        err = "agent_result missing"
        logger.error("%s task_id=%s", err, task.get("task_id"))
        errors.append({"node": "process_result", "task_id": task.get("task_id"), "error": err})
        for item in checklist:
            if item.get("task_id") == task.get("task_id"):
                item["status"] = "failed"
                item["error"] = err
                break
        return {"checklist": checklist, "errors": errors, "agent_result": None}

    task_id = res.get("task_id") or task.get("task_id")
    agent = (res.get("agent") or task.get("agent") or "").strip()
    status = (res.get("status") or "").strip()

    # ponytail: store full envelope keyed by agent, overwrite last; no per-task dict until need
    if agent:
        agent_results[agent] = res

    # update checklist item
    for item in checklist:
        if item.get("task_id") == task_id:
            if status in ("success", "searched", "fallback", "partial"):
                item["status"] = "success"
                item["error"] = None
            elif status == "no_results":
                # ponytail: no_results treated as success with empty result, not failure
                item["status"] = "success"
                item["error"] = None
            else:
                item["status"] = "failed"
                item["error"] = res.get("error")
            break

    if status not in ("success", "searched", "fallback", "partial", "no_results"):
        errors.append({"node": "process_result", "task_id": task_id, "agent": agent, "error": res.get("error") or status})

    logger.info("process_result task_id=%s agent=%s status=%s checklist=%s", task_id, agent, status, len(checklist))
    # ponytail: clear transient agent_result, keep current_task for trace until next select
    return {"checklist": checklist, "agent_results": agent_results, "errors": errors, "agent_result": None}
