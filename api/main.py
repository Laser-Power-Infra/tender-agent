import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlmodel import Session, select

from lib.core.webhook_events import WEBHOOK_EVENTS
from lib.database.connection import get_session
from lib.database.models import Webhook, new_webhook_secret
from agents.intelligence.subagents.item.graph import get_item_graph
from agents.intelligence.subagents.search.graph import get_search_graph
from agents.relevance.nodes.category import add_category_feedback
from agents.relevance.prompts import PROMPTS

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
    item_names: list[str] = Field(default_factory=list)
    status: str
    error: str | None = None


class CategoryFeedbackRequest(BaseModel):
    model_config = {"populate_by_name": True}

    brief: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    reference_no: str | None = Field(default=None, alias="referenceNo")
    note: str | None = None


class CategoryFeedbackResponse(BaseModel):
    id: str
    status: str


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
    graph = get_item_graph()
    result = graph.invoke({"item_category": category})
    return ItemResponse(
        item_category=category,
        item_names=result.get("item_names") or [],
        status=result.get("status") or "unknown",
        error=result.get("error"),
    )


@app.post("/category-feedback", response_model=CategoryFeedbackResponse, status_code=201)
def category_feedback(req: CategoryFeedbackRequest):
    company, category = req.company.strip().lower(), req.category.strip().lower()
    if f"{company}_{category}" not in PROMPTS:
        raise HTTPException(status_code=422, detail=f"unknown category {category!r} for company {company!r}")
    ref = (req.reference_no or "").strip() or None
    point_id = add_category_feedback(req.brief.strip(), company, category, ref, req.note)
    return CategoryFeedbackResponse(id=point_id, status="indexed")


# --- Webhook registration -------------------------------------------------

WebhookEvent = Literal[tuple(WEBHOOK_EVENTS)]  # type: ignore[valid-type]


def _dedupe_events(events: list[str] | None) -> list[str] | None:
    return None if events is None else list(dict.fromkeys(events))


class WebhookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: HttpUrl
    events: list[WebhookEvent] = Field(..., min_length=1)

    _dedupe = field_validator("events")(_dedupe_events)


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: HttpUrl | None = None
    events: list[WebhookEvent] | None = Field(default=None, min_length=1)
    is_active: bool | None = None

    _dedupe = field_validator("events")(_dedupe_events)


class WebhookOut(BaseModel):
    id: int
    name: str
    url: str
    client_id: str
    secret: str
    events: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


def _get_webhook(session: Session, webhook_id: int) -> Webhook:
    webhook = session.get(Webhook, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


def _save(session: Session, webhook: Webhook) -> Webhook:
    session.add(webhook)
    session.commit()
    session.refresh(webhook)
    return webhook


@app.get("/webhooks", include_in_schema=False)
def webhooks_page():
    return FileResponse(Path(__file__).parent / "static" / "webhooks.html")


@app.get("/api/webhooks/events")
def list_webhook_events():
    return [{"name": name, "description": desc} for name, desc in WEBHOOK_EVENTS.items()]


@app.get("/api/webhooks", response_model=list[WebhookOut])
def list_webhooks(session: Session = Depends(get_session)):
    return session.exec(select(Webhook).order_by(Webhook.id.desc())).all()


@app.post("/api/webhooks", response_model=WebhookOut, status_code=201)
def create_webhook(req: WebhookCreate, session: Session = Depends(get_session)):
    return _save(session, Webhook(name=req.name.strip(), url=str(req.url), events=req.events))


@app.patch("/api/webhooks/{webhook_id}", response_model=WebhookOut)
def update_webhook(webhook_id: int, req: WebhookUpdate, session: Session = Depends(get_session)):
    webhook = _get_webhook(session, webhook_id)
    changes = req.model_dump(exclude_none=True)
    if "url" in changes:
        changes["url"] = str(req.url)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    for key, value in changes.items():
        setattr(webhook, key, value)
    return _save(session, webhook)


@app.post("/api/webhooks/{webhook_id}/rotate-secret", response_model=WebhookOut)
def rotate_webhook_secret(webhook_id: int, session: Session = Depends(get_session)):
    webhook = _get_webhook(session, webhook_id)
    webhook.secret = new_webhook_secret()
    return _save(session, webhook)


@app.delete("/api/webhooks/{webhook_id}", status_code=204)
def delete_webhook(webhook_id: int, session: Session = Depends(get_session)):
    session.delete(_get_webhook(session, webhook_id))
    session.commit()
