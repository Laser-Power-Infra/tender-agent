import logging

from langgraph.graph import END, START, StateGraph

from intelligence.nodes.analyze_request import analyze_request
from intelligence.nodes.call_sub_agent import call_sub_agent
from intelligence.nodes.create_checklist import create_checklist
from intelligence.nodes.more_tasks import more_tasks
from intelligence.nodes.process_result import process_result
from intelligence.nodes.select_next_task import select_next_task
from intelligence.nodes.synthesize_final_result import synthesize_final_result
from intelligence.state import IntelligenceState

logger = logging.getLogger(__name__)


def build_intelligence_graph(checkpointer=None):
    logger.info("Building intelligence graph checkpointer=%s", bool(checkpointer))
    graph = StateGraph(IntelligenceState)
    graph.add_node("analyze_request", analyze_request)
    graph.add_node("create_checklist", create_checklist)
    graph.add_node("select_next_task", select_next_task)
    graph.add_node("call_sub_agent", call_sub_agent)
    graph.add_node("process_result", process_result)
    graph.add_node("synthesize_final_result", synthesize_final_result)
    graph.add_edge(START, "analyze_request")
    graph.add_edge("analyze_request", "create_checklist")
    graph.add_edge("create_checklist", "select_next_task")
    graph.add_edge("select_next_task", "call_sub_agent")
    graph.add_edge("call_sub_agent", "process_result")
    graph.add_conditional_edges(
        "process_result",
        more_tasks,
        {"continue": "select_next_task", "complete": "synthesize_final_result"},
    )
    graph.add_edge("synthesize_final_result", END)
    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    # ponytail: hard loop cap 25 steps, prevents infinite pending loop; GraphRecursionError if exceeded
    compiled = compiled.with_config(recursion_limit=25)
    logger.info("Intelligence graph compiled checkpointer=%s", bool(checkpointer))
    return compiled
