from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from intelligence.state import keep_first_error, keep_first_failure


class ItemNameResult(BaseModel):
    item_name: str = Field(..., description="generated item name for the category")


class ItemState(TypedDict, total=False):
    # input: which item-knowledge category to search
    item_category: str
    # ReAct conversation: LLM messages + ToolMessages appended by the tools node
    messages: Annotated[list, add_messages]
    # output: the generated item name
    item_name: str
    status: Annotated[str, keep_first_failure]
    error: Annotated[str | None, keep_first_error]