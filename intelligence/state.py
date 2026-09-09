from typing import TypedDict


class IntelligenceState(TypedDict, total=False):
    reference_no: str
    search_plan: list[dict]
    search_results: list[dict]
    status: str
    error: str | None
