"""Supply history + item schedule for each certificate, from the tender-executive-dashboard MCP.

A party reference that matches supply history already carries the item schedules and the
party name, so nothing else is searched: JEV only decides whether the certificate's issuer
and the supply-history party are the same party. Same party -> reuse those details.
No match (or a different party) -> one LLM call maps the certificate items onto the
catalog schedules from list_item_categories. Any MCP failure degrades to empty fields.
"""

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel

from lib.core.config import settings
from lib.core.llm import get_llm
from agents.performance_cert.nodes.decide import MIN_CONFIDENCE
from lib.core.jev import get_jev

logger = logging.getLogger(__name__)

PARTY_CHOICES = ("same", "different", "needs_review")

SCHEDULE_PROMPT = (
    "Map each item from a performance certificate of a cable and conductor manufacturer "
    "onto one item schedule from the catalog list below. Copy the schedule name exactly. "
    "Use null when no schedule clearly fits. Never invent a schedule.\n\n"
    "Catalog schedules (schedule, item count, example item name):\n{categories}\n\n"
    "Certificate items:\n{items}"
)


class ItemPick(BaseModel):
    item: str
    schedule: str | None = None


class SchedulePicks(BaseModel):
    picks: list[ItemPick] = []


def _blank() -> dict:
    return {
        "supply_history": [],
        "supply_party_name": None,
        "party_match": None,
        "item_schedules": [],
        "item_schedule_source": None,
    }


def _distinct(values) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))


def _party_match(ref: str | None, cert_party: str | None, supply_parties: list[str], party_ref_no: str) -> str:
    """same | different | needs_review. Plain equal names skip JEV; a JEV failure is needs_review."""
    if not cert_party:
        return "needs_review"
    if cert_party.strip().casefold() in {p.casefold() for p in supply_parties}:
        return "same"
    try:
        from typesafe_sdk import Choice

        result = get_jev(settings.typesafe_api_key, settings.typesafe_model).system_one(
            state={
                "party_reference_no": party_ref_no,
                "certificate_issuer": cert_party,
                "supply_history_parties": supply_parties,
            },
            questions={
                "party": Choice(
                    instructions=(
                        "A performance certificate and supply-history (sale bill) rows share the same party "
                        "reference number. Decide if the certificate issuer and the supply-history party are the "
                        "same organisation. Abbreviations, expansions, office/division/circle names of the same "
                        "organisation, and spelling or punctuation variants count as the same party. "
                        "A different company, or an end utility versus its contractor, is a different party."
                    ),
                    criteria={
                        "same": "both names refer to the same organisation",
                        "different": "the names refer to different organisations",
                        "needs_review": "the names are too vague or contradictory to decide",
                    },
                ),
            },
        )
        answer = result.choices["party"]
        decision = str(answer.choice or "").strip()
        confidence = float(answer.confidence or 0.0)
        logger.info("party jev ref=%s choice=%s confidence=%.3f", ref, decision, confidence)
        if decision not in PARTY_CHOICES or confidence < MIN_CONFIDENCE:
            return "needs_review"
        return decision
    except Exception as e:
        logger.error("party jev ref=%s error=%s", ref, f"{type(e).__name__}: {e}", exc_info=True)
        return "needs_review"


def _catalog_schedules(items: list[str], categories: list[dict]) -> list[str]:
    known = {c["schedule"] for c in categories if c.get("schedule")}
    lines = "\n".join(f"- {c['schedule']} ({c.get('count')}): {c.get('example')}" for c in categories)
    res = get_llm().with_structured_output(SchedulePicks).invoke(
        SCHEDULE_PROMPT.format(categories=lines, items="\n".join(f"- {i}" for i in items))
    )
    return _distinct(p.schedule for p in (res.picks if res else []) if p.schedule in known)


async def _enrich(ref: str | None, details: list[dict], call) -> list[dict]:
    """call(tool_name, args) -> structuredContent dict."""
    categories: list[dict] | None = None
    out = []
    for d in details:
        entry = {**d, **_blank()}
        try:
            party_ref_no = (d.get("party_reference_no") or "").strip()
            if party_ref_no:
                rows = (await call("search_supply_history", {"partyRefNo": party_ref_no, "limit": 200})).get("rows") or []
                entry["supply_history"] = rows
                if rows:
                    parties = _distinct(r.get("partyName") for r in rows)
                    entry["supply_party_name"] = parties[0] if parties else None
                    entry["party_match"] = _party_match(ref, d.get("party_name"), parties, party_ref_no)
                    if entry["party_match"] == "same":
                        entry["item_schedules"] = _distinct(r.get("itemSchedule") for r in rows)
                        entry["item_schedule_source"] = "supply_history" if entry["item_schedules"] else None
                        entry["party_name"] = entry["supply_party_name"] or d.get("party_name")

            items = d.get("items") or []
            if not entry["item_schedules"] and items:
                if categories is None:
                    categories = (await call("list_item_categories", {})).get("categories") or []
                entry["item_schedules"] = _catalog_schedules(items, categories)
                entry["item_schedule_source"] = "catalog" if entry["item_schedules"] else None
        except Exception as e:
            logger.error("lookup ref=%s cert=%s error=%s", ref, d.get("certificate_id"), f"{type(e).__name__}: {e}", exc_info=True)
        out.append(entry)
    return out


async def _run(ref: str | None, details: list[dict], url: str, key: str) -> list[dict]:
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    # same timeouts the deprecated streamablehttp_client used: 30s, 300s read for the SSE stream
    http = httpx.AsyncClient(headers={"x-api-key": key}, timeout=httpx.Timeout(30, read=300))
    async with http, streamable_http_client(url, http_client=http) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name: str, args: dict) -> dict:
                res = await session.call_tool(name, args)
                if res.isError:
                    raise RuntimeError(f"{name}: {' '.join(getattr(c, 'text', '') for c in res.content)}")
                return res.structuredContent or json.loads(res.content[0].text)

            return await _enrich(ref, details, call)


def lookup(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: adds supply history, party match and item schedules to each detail."""
    ref = (state.get("job_id") or "").strip() or None
    details = state.get("details") or []
    if not details:
        return {"details": []}

    url, key = settings.dashboard_mcp_url, settings.dashboard_api_key
    if not url or not key:
        logger.warning("lookup ref=%s DASHBOARD_MCP_URL / DASHBOARD_API_KEY unset, skipped", ref)
        return {"details": [{**d, **_blank()} for d in details]}
    try:
        out = asyncio.run(_run(ref, details, url, key))
    except Exception as e:
        logger.error("lookup ref=%s mcp error=%s", ref, f"{type(e).__name__}: {e}", exc_info=True)
        out = [{**d, **_blank()} for d in details]

    logger.info("lookup ref=%s files=%d", ref, len(out))
    return {"details": out}


if __name__ == "__main__":
    import sys
    import types

    rows = [
        {"partyName": "WBSEDCL", "itemSchedule": "HT XLPE CABLE", "itemName": "3C X 300"},
        {"partyName": "WBSEDCL", "itemSchedule": "HT XLPE CABLE", "itemName": "3C X 185"},
    ]
    categories = [{"schedule": "LT ABC", "count": 3, "example": "3X50+1X35 ABC"}, {"schedule": "HT XLPE CABLE", "count": 9, "example": "3C X 300"}]
    calls = []

    def fake_call(supply):
        async def call(name, args):
            calls.append(name)
            if name == "search_supply_history":
                return {"rows": supply}
            return {"categories": categories}
        return call

    g = _enrich.__globals__
    jev = types.SimpleNamespace(choices={"party": types.SimpleNamespace(choice="same", confidence=0.9)})
    g["get_jev"] = lambda *a: types.SimpleNamespace(system_one=lambda **kw: jev)
    sys.modules["typesafe_sdk"] = types.SimpleNamespace(Choice=lambda **kw: kw)
    picks = SchedulePicks(picks=[ItemPick(item="x", schedule="LT ABC"), ItemPick(item="y", schedule="MADE UP")])
    g["get_llm"] = lambda: types.SimpleNamespace(
        with_structured_output=lambda _: types.SimpleNamespace(invoke=lambda _p: picks)
    )

    base = {"certificate_id": "C1", "party_reference_no": "LC/1", "party_name": "W.B.S.E.D.C.L.", "items": ["a"]}

    # ref matches + JEV says same -> reuse supply schedules and party name, no catalog call
    [r] = asyncio.run(_enrich("R1", [base], fake_call(rows)))
    assert r["party_match"] == "same" and r["item_schedules"] == ["HT XLPE CABLE"], r
    assert r["item_schedule_source"] == "supply_history" and r["party_name"] == "WBSEDCL", r
    assert calls == ["search_supply_history"], calls

    # JEV says different -> supply not reused, catalog picks only known schedules
    jev.choices["party"].choice = "different"
    calls.clear()
    [r] = asyncio.run(_enrich("R2", [base], fake_call(rows)))
    assert r["party_match"] == "different" and r["party_name"] == "W.B.S.E.D.C.L.", r
    assert r["item_schedules"] == ["LT ABC"] and r["item_schedule_source"] == "catalog", r

    # low confidence -> needs_review
    jev.choices["party"].choice, jev.choices["party"].confidence = "same", 0.3
    [r] = asyncio.run(_enrich("R3", [base], fake_call(rows)))
    assert r["party_match"] == "needs_review", r

    # exact name -> same without JEV
    g["get_jev"] = lambda *a: (_ for _ in ()).throw(AssertionError("jev called"))
    [r] = asyncio.run(_enrich("R4", [{**base, "party_name": "wbsedcl"}], fake_call(rows)))
    assert r["party_match"] == "same", r

    # no supply rows -> catalog
    [r] = asyncio.run(_enrich("R5", [base], fake_call([])))
    assert r["party_match"] is None and r["item_schedule_source"] == "catalog", r

    # tool error -> blank fields, entry kept
    async def boom(name, args):
        raise RuntimeError("down")

    [r] = asyncio.run(_enrich("R6", [base], boom))
    assert r["certificate_id"] == "C1" and r["supply_history"] == [] and r["item_schedules"] == [], r

    # unset config -> skipped, details kept
    settings.dashboard_mcp_url = None
    r = lookup({"job_id": "R7", "details": [base]})
    assert r["details"][0]["certificate_id"] == "C1" and r["details"][0]["party_match"] is None, r
    print("lookup ok")
