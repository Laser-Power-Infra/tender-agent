import operator
from typing import Annotated, Literal, TypedDict


class ChecklistItem(TypedDict, total=False):
    task_id: str
    agent: str
    description: str
    status: Literal["pending", "running", "success", "failed", "skipped"]
    result_key: str | None
    error: str | None


# Subagent status vocabulary. Lives here, not in run_task: every node and both subgraph states need
# it, and importing run_task drags in the whole specialized graph, which drags in core.config.
#
# Three classes, because "the tender does not mention this" and "the llm was down" are different
# answers and used to be the same one:
#   FAILED_STATUSES   — the node could not do its job. Nothing downstream should treat this as data.
#   DEGRADED_STATUSES — something came back, but not by the intended path. Not a failure, not a
#                       clean answer; the caller has to be told which.
#   everything else   — completed. "no_results"/"no_valid"/"no_hits" are real answers: the search ran
#                       and the tender genuinely says nothing.
FAILED_STATUSES = frozenset({"failed", "no_plan"})
DEGRADED_STATUSES = frozenset({"fallback", "rerank_fallback", "partial"})

# ponytail: was OK_STATUSES, which counted "fallback" and "partial" as success — an llm outage and a
# real answer produced the same checklist entry. Kept as a name because run_task and
# synthesize_final_result both ask the same question.
def is_done(status: str | None) -> bool:
    """True when the task actually completed. Degraded counts as done but is reported separately."""
    return status not in FAILED_STATUSES


def keep_first_failure(left: str | None, right: str | None) -> str:
    """Reducer for subagent `status`: a failure sticks, later nodes cannot paper over it.

    Both subgraphs are unconditional linear chains, so without this the last node's status
    overwrites the failing node's — generate_queries "failed" became execute_search "no_plan"
    became synthesize "no_results", and run_task recorded a success.
    """
    if left in FAILED_STATUSES:
        return left
    return right if right is not None else left


def keep_first_error(left: str | None, right: str | None) -> str | None:
    """Reducer for subagent `error`: first real error wins, a later None cannot clear it."""
    return left if left else right


def merge_agent_results(left: dict | None, right: dict | None) -> dict:
    """Reducer: tasks run in parallel and each writes its own agent key."""
    return {**(left or {}), **(right or {})}


def merge_checklist(left: list | None, right: list | None) -> list:
    """Reducer: replace an item by task_id, append if new. Order stays as create_checklist set it."""
    out = list(left or [])
    at = {item.get("task_id"): i for i, item in enumerate(out)}
    for item in right or []:
        task_id = item.get("task_id")
        if task_id in at:
            out[at[task_id]] = item
        else:
            at[task_id] = len(out)
            out.append(item)
    return out


class IntelligenceState(TypedDict, total=False):
    # original request
    reference_no: str
    user_query: str
    # "gem" | "non_gem" | "" — routes which document sections run, see document_agents
    tender_type: str
    # parsed understanding
    parsed_request: dict
    # checklist is central control — reduced because run_task writes to it in parallel
    checklist: Annotated[list[ChecklistItem], merge_checklist]
    # fan-out payload: one Send per pending task carries these
    task: ChecklistItem
    agent: str
    # collected results
    agent_results: Annotated[dict, merge_agent_results]
    errors: Annotated[list[dict], operator.add]
    final_response: dict
