from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

from intelligence.state import keep_first_error, keep_first_failure


class QueryPlan(BaseModel):
    queries: list[str] = Field(description="2-5 search queries for the item-knowledge collection")


class ItemNameResult(BaseModel):
    item_names: list[str] = Field(..., description="exact item names from the catalog, or ['not found']")


class ItemState(TypedDict, total=False):
    # input: which item-knowledge category to search
    item_category: str
    # generated search queries
    queries: list[str]
    # hybrid search results
    hits: list[dict]
    # output: the decided item name(s)
    item_names: list[str]
    status: Annotated[str, keep_first_failure]
    error: Annotated[str | None, keep_first_error]