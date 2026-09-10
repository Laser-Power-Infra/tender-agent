from typing import TypedDict


class SpecializedState(TypedDict, total=False):
    reference_no: str
    user_query: str
    parsed_request: dict
    task: dict
    agent: str
    system_prompt: str
    query_pairs: list[dict]
    search_results: list[dict]
    sources: list[dict]
    result: dict
    status: str
    error: str | None
