from typing import Any, TypedDict


class RelevanceState(TypedDict, total=False):
    payload_type: str
    reference_no: str
    company: str
    category: str
    tender_amount: float | str | None
    extra: dict[str, Any]

    # feedback branch
    chunk: str
    vector_ids: list[str]
    status: str
    error: str | None

    # analysis branch
    brief: str
    itemcategory: str
    hits: list[dict]
    verdict: dict
    webhook: dict