from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from intelligence.subagents.search.graph import get_search_graph

app = FastAPI(title="tender-agent")


class SearchRequest(BaseModel):
    model_config = {"populate_by_name": True}

    query: str = Field(..., min_length=1)
    keywords: list[str] = Field(default_factory=list)
    reference_no: str | None = Field(default=None, alias="referenceNo")


class SearchResponse(BaseModel):
    query: str
    keywords: list[str]
    reference_no: str | None = None
    status: str
    hits: list[dict] = Field(default_factory=list)
    reranked: list[dict] = Field(default_factory=list)
    valid: list[dict] = Field(default_factory=list)
    error: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=422, detail="query is required")
    graph = get_search_graph()
    result = graph.invoke(
        {"query": q, "keywords": req.keywords or [], "reference_no": req.reference_no}
    )
    return SearchResponse(
        query=q,
        keywords=req.keywords or [],
        reference_no=req.reference_no,
        status=result.get("status") or "unknown",
        hits=result.get("hits") or [],
        reranked=result.get("reranked") or [],
        valid=result.get("valid") or [],
        error=result.get("error"),
    )
