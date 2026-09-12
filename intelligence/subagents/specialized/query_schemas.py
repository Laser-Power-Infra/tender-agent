from pydantic import BaseModel, Field


class QueryItem(BaseModel):
    # ponytail: the join key execute_search groups by. Defaulted, not required: reverse_auction,
    # basic_details and emd_agent share this schema and their prompts ask for "parameter", so a
    # required field would force those models to invent a document name.
    document: str = Field(default="", description="exact document/parameter name as given, unchanged — join key")
    query: str = Field(description="natural question to search")
    keywords: list[str] = Field(description="2-5 keywords for hybrid search")


class QueryPairs(BaseModel):
    items: list[QueryItem] = Field(description="array of query+keywords")
