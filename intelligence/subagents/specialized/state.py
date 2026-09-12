from typing import Annotated, TypedDict

from intelligence.state import keep_first_error, keep_first_failure


class SpecializedState(TypedDict, total=False):
    reference_no: str
    task: dict
    agent: str
    query_pairs: list[dict]
    search_results: list[dict]
    sources: list[dict]
    result: dict
    # reduced: generate_queries -> execute_search -> synthesize is an unconditional chain, so a plain
    # key let the last node overwrite the failing node's status and error with its own
    status: Annotated[str, keep_first_failure]
    error: Annotated[str | None, keep_first_error]
