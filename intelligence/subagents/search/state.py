from typing import TypedDict


class SearchState(TypedDict, total=False):
    query: str
    keywords: list[str]
    reference_no: str | None
    hits: list[dict]
    reranked: list[dict]
    valid: list[dict]
    status: str
    error: str | None
