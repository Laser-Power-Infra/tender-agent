import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from intelligence.subagents.item.graph import get_item_graph
from intelligence.subagents.search.graph import get_search_graph

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

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


class ItemRequest(BaseModel):
    item_category: str = Field(..., min_length=1)


class ItemResponse(BaseModel):
    item_category: str
    item_name: str
    status: str
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


@app.post("/item", response_model=ItemResponse)
def item(req: ItemRequest):
    category = req.item_category.strip()
    if not category:
        raise HTTPException(status_code=422, detail="item_category is required")
    graph = get_item_graph(category)
    result = graph.invoke({"item_category": category})
    return ItemResponse(
        item_category=category,
        item_name=result.get("item_name") or "",
        status=result.get("status") or "unknown",
        error=result.get("error"),
    )
