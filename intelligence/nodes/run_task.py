import logging

from intelligence.state import DEGRADED_STATUSES, IntelligenceState, is_done
from intelligence.subagents.specialized.graph import get_specialized_graph

logger = logging.getLogger(__name__)


def run_task(state: IntelligenceState) -> dict:
    """One checklist task, start to finish. Receives a Send payload, not the whole state.

    ponytail: was call_sub_agent + process_result + select_next_task + more_tasks driving a
    serial loop. Tasks are independent, so the graph fans them out and this node is the whole body.
    """
    task = state.get("task") or {}
    reference_no = (state.get("reference_no") or "").strip()
    task_id = task.get("task_id")
    agent = (state.get("agent") or task.get("agent") or "").strip()

    if not agent:
        err = "agent missing in task"
        logger.error("%s task_id=%s", err, task_id)
        return {
            "checklist": [{**task, "status": "failed", "error": err}],
            "errors": [{"node": "run_task", "task_id": task_id, "error": err}],
        }

    try:
        out = get_specialized_graph().invoke({"reference_no": reference_no, "task": task, "agent": agent})
        status = out.get("status") or "success"
        envelope = {
            "task_id": task_id,
            "agent": agent,
            "status": status,
            "result": out.get("result") or {},
            "sources": out.get("sources") or [],
            "error": out.get("error"),
        }
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("run_task failed task_id=%s agent=%s error=%s", task_id, agent, err, exc_info=True)
        return {
            "checklist": [{**task, "status": "failed", "error": err}],
            "agent_results": {agent: {"task_id": task_id, "agent": agent, "status": "failed", "result": {}, "sources": [], "error": err}},
            "errors": [{"node": "run_task", "task_id": task_id, "agent": agent, "error": err}],
        }

    # ponytail: no_results is an answer, not a failure. A degraded status (fallback/partial) is
    # neither — the task finished, but not by the intended path, so it is recorded as done and
    # surfaced separately rather than silently counted as a clean success.
    done = is_done(status)
    if status in DEGRADED_STATUSES:
        logger.warning("run_task degraded task_id=%s agent=%s status=%s error=%s", task_id, agent, status, envelope["error"])
    logger.info("run_task done task_id=%s agent=%s status=%s sources=%s", task_id, agent, status, len(envelope["sources"]))
    return {
        "checklist": [{**task, "status": "success" if done else "failed", "error": None if done else envelope["error"]}],
        # ponytail: keyed by task_id, not agent — two tasks for one agent no longer overwrite each other
        "agent_results": {task_id or agent: envelope},
        "errors": [] if done else [{"node": "run_task", "task_id": task_id, "agent": agent, "error": envelope["error"] or status}],
    }
