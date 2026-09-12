from typing import Annotated, TypedDict

from intelligence.state import keep_first_error, keep_first_failure


class SearchState(TypedDict, total=False):
    query: str
    keywords: list[str]
    reference_no: str | None
    hits: list[dict]
    reranked: list[dict]
    valid: list[dict]
    # reduced: hybrid_search -> rerank is an unconditional chain, so a failed search used to reach
    # the caller as rerank's clean "no_hits" with error=None
    status: Annotated[str, keep_first_failure]
    error: Annotated[str | None, keep_first_error]
