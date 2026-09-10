from pydantic import BaseModel, Field


class QueryItem(BaseModel):
    query: str = Field(description="natural question to search")
    keywords: list[str] = Field(description="2-5 keywords for hybrid search")


class QueryPairs(BaseModel):
    items: list[QueryItem] = Field(description="array of query+keywords")


# ponytail: the per-agent document schema went away with the company_document_finder LLM call —
# that checklist is static now, see company_documents.py. Add a model back when an agent needs one.
