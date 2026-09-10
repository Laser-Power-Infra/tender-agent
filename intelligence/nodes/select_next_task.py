import logging

from intelligence.state import IntelligenceState

logger = logging.getLogger(__name__)

def select_next_task(state: IntelligenceState) -> dict:
    checklist = state.get("checklist") or []
    for task in checklist:
        if task.get("status") == "pending":
            task["status"] = "running"
            logger.info("select_next_task running task_id=%s agent=%s", task.get("task_id"), task.get("agent"))
            return {"current_task": task, "checklist": checklist}
    logger.info("select_next_task none pending=%s", len(checklist))
    return {"current_task": None}
