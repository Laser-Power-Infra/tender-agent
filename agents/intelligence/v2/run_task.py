import logging

from langgraph.errors import GraphRecursionError

from agents.intelligence.nodes.run_task import run_task as run_task_v1
from agents.intelligence.state import DEGRADED_STATUSES, is_done
from agents.intelligence.subagents.specialized.schemas import AGENT_OUTPUT_MODELS
from agents.intelligence.v2.agent import _RECURSION_LIMIT, V2_AGENTS, build_agent
from lib.core.llm import get_llm

logger = logging.getLogger(__name__)

_SALVAGE_PROMPT = "Answer now from the chunks above. Leave fields the chunks do not state empty."
_STEP_LIMIT_MSG = "Sorry, need more steps to process this request."  # langgraph/prebuilt/chat_agent_executor.py
_MODEL = None  # tests inject a fake chat model here


def _finalize(messages, OutputModel):
    """One structured call over the agent transcript. Same path for a normal end and a recursion salvage."""
    return get_llm().with_structured_output(OutputModel).invoke(list(messages) + [("human", _SALVAGE_PROMPT)])


def run_task(state: dict) -> dict:
    """v2 body for one checklist task. Reasoning agents run the ReAct loop; everything else is v1."""
    task = state.get("task") or {}
    agent = (state.get("agent") or task.get("agent") or "").strip()
    if agent not in V2_AGENTS:
        return run_task_v1(state)

    reference_no = (state.get("reference_no") or "").strip()
    task_id = task.get("task_id")
    OutputModel = AGENT_OUTPUT_MODELS[agent]
    sources: list[dict] = []
    status, error, last = "success", None, {"messages": []}
    try:
        graph = build_agent(agent, reference_no, sources, model=_MODEL)
        for last in graph.stream({"messages": [("human", f"Analyse tender {reference_no}")]}, stream_mode="values"):
            pass
    except GraphRecursionError:
        status = "partial"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("v2 run_task failed task_id=%s agent=%s error=%s", task_id, agent, err, exc_info=True)
        return {
            "checklist": [{**task, "status": "failed", "error": err}],
            "agent_results": {task_id or agent: {"task_id": task_id, "agent": agent, "status": "failed", "result": {}, "sources": [], "error": err}},
            "errors": [{"node": "run_task", "task_id": task_id, "agent": agent, "error": err}],
        }

    messages = list(last.get("messages") or [])
    # create_react_agent does not raise at the limit: it answers with a canned message instead
    if messages and getattr(messages[-1], "content", None) == _STEP_LIMIT_MSG:
        status, messages = "partial", messages[:-1]
    if status == "partial":
        searches = sum(1 for m in messages if getattr(m, "type", "") == "tool")
        error = f"recursion limit {_RECURSION_LIMIT} hit after {searches} searches"

    try:
        result = _finalize(messages, OutputModel).model_dump()
    except Exception as e:
        status, error = "failed", f"{type(e).__name__}: {e}"
        result = OutputModel().model_dump()
        logger.error("v2 finalize failed task_id=%s agent=%s error=%s", task_id, agent, error, exc_info=True)

    envelope = {"task_id": task_id, "agent": agent, "status": status, "result": result, "sources": sources, "error": error}
    done = is_done(status)
    if status in DEGRADED_STATUSES:
        logger.warning("v2 run_task degraded task_id=%s agent=%s status=%s error=%s", task_id, agent, status, error)
    logger.info("v2 run_task done task_id=%s agent=%s status=%s sources=%s", task_id, agent, status, len(sources))
    return {
        "checklist": [{**task, "status": "success" if done else "failed", "error": None if done else error}],
        "agent_results": {task_id or agent: envelope},
        "errors": [] if done else [{"node": "run_task", "task_id": task_id, "agent": agent, "error": error or status}],
    }
