from typing import TypedDict


class SpecializedState(TypedDict, total=False):
    reference_no: str
    task: dict
    agent: str
    query_pairs: list[dict]
    search_results: list[dict]
    sources: list[dict]
    result: dict
    status: str
    error: str | None
