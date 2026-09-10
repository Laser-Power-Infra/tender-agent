from typing import Literal, TypedDict


class ChecklistItem(TypedDict, total=False):
    task_id: str
    agent: str
    description: str
    status: Literal["pending", "running", "success", "failed", "skipped"]
    result_key: str | None
    error: str | None


class IntelligenceState(TypedDict, total=False):
    # original request
    reference_no: str
    user_query: str
    # parsed understanding
    parsed_request: dict
    # checklist is central control
    checklist: list[ChecklistItem]
    current_task: ChecklistItem | None
    # collected results
    agent_results: dict
    errors: list[dict]
    final_response: dict
