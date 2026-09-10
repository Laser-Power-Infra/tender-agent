from pydantic import BaseModel, Field


class QueryItem(BaseModel):
    query: str = Field(description="natural question to search")
    keywords: list[str] = Field(description="2-5 keywords for hybrid search")


class QueryPairs(BaseModel):
    items: list[QueryItem] = Field(description="array of query+keywords")


# ponytail: base document structure per schema {document, query, keywords 4-8}, extended by company
class BaseDocumentQueryItem(BaseModel):
    document: str = Field(description="exact checklist item name, unchanged")
    query: str = Field(description="natural question to find if document required")
    keywords: list[str] = Field(description="4-8 keyword variants", min_length=4, max_length=8)
    model_config = {"extra": "forbid"}


class BaseDocumentQueryPairs(BaseModel):
    items: list[BaseDocumentQueryItem] = Field(description="array of document query items")


class CompanyDocQueryItem(BaseDocumentQueryItem):
    pass


class CompanyDocQueryPairs(BaseDocumentQueryPairs):
    pass


# ponytail: single source for query schema, agent -> model, like AGENT_PROMPTS/AGENT_OUTPUT_MODELS
AGENT_QUERY_MODELS: dict[str, type[BaseModel]] = {
    "company_document_finder": CompanyDocQueryPairs,
}
DEFAULT_QUERY_MODEL = QueryPairs
