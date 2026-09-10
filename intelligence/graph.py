import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from intelligence.nodes.analyze_request import analyze_request
from intelligence.nodes.create_checklist import create_checklist
from intelligence.nodes.run_task import run_task
from intelligence.nodes.synthesize_final_result import synthesize_final_result
from intelligence.state import IntelligenceState

logger = logging.getLogger(__name__)

# ponytail: tasks are independent, so bound the fan-out by what Qdrant/OpenAI tolerate, not by the
# checklist length. 8 x execute_search's 4 = the same ~32 in-flight searches as the old 5 x 8, but
# 8 sections can overlap their synthesis call instead of 5 — with 47 tasks that is 6 waves, not 10.
_TASK_CONCURRENCY = 8


def fan_out_tasks(state: IntelligenceState):
    """One Send per pending task. Nothing in a task reads another task's result."""
    pending = [t for t in (state.get("checklist") or []) if t.get("status") == "pending"]
    if not pending:
        logger.info("no pending tasks, going straight to synthesis")
        return "synthesize_final_result"
    logger.info("fanning out %s tasks", len(pending))
    return [
        Send("run_task", {"reference_no": state.get("reference_no") or "", "task": t, "agent": t.get("agent")})
        for t in pending
    ]


def build_intelligence_graph(checkpointer=None):
    logger.info("Building intelligence graph checkpointer=%s", bool(checkpointer))
    graph = StateGraph(IntelligenceState)
    graph.add_node("analyze_request", analyze_request)
    graph.add_node("create_checklist", create_checklist)
    graph.add_node("run_task", run_task)
    graph.add_node("synthesize_final_result", synthesize_final_result)
    graph.add_edge(START, "analyze_request")
    graph.add_edge("analyze_request", "create_checklist")
    graph.add_conditional_edges("create_checklist", fan_out_tasks, ["run_task", "synthesize_final_result"])
    graph.add_edge("run_task", "synthesize_final_result")
    graph.add_edge("synthesize_final_result", END)
    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    # ponytail: depth is now fixed at 4 supersteps whatever the checklist length, so the limit is only a runaway guard
    compiled = compiled.with_config(recursion_limit=25, max_concurrency=_TASK_CONCURRENCY)
    logger.info("Intelligence graph compiled checkpointer=%s", bool(checkpointer))
    return compiled
