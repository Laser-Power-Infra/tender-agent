import operator
from typing import Annotated, Literal, TypedDict


class ChecklistItem(TypedDict, total=False):
    task_id: str
    agent: str
    description: str
    status: Literal["pending", "running", "success", "failed", "skipped"]
    result_key: str | None
    error: str | None


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
