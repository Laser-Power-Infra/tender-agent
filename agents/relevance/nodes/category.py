import logging
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, PointStruct

from lib.core.config import settings
from lib.core.llm import get_llm
from agents.relevance.nodes.feedback import brief_of
from agents.relevance.prompts import CATEGORY_PICK, EPC_CATEGORIES, PROMPTS
from lib.vector.embeddings import get_dense
from lib.vector.qdrant import ensure_collection, qdrant

logger = logging.getLogger(__name__)

# ponytail: rules first (keyword + voltage, plain code), an LLM only for work tenders no rule can place.
# The old all-LLM version returned null even for "132/33 kv substation" and "distribution transformer".
SUBSTATION = re.compile(r"sub[\s-]?stations?\b|\bs/s\b")
# supply-only = a supply word and no work word. Only the cable prompt accepts supply-only; every EPC prompt rejects it.
SUPPLY = re.compile(r"\bsuppl|\bprocure|\bpurchase|\bdeliver|rate contract")
WORK = re.compile(r"erect|\bstring|install|\blay|commission|construct|turnkey|\bepc\b|\bsitc\b")
CABLE = re.compile(r"\bcables?\b|\bconductors?\b|\bacsr\b|\baaac?\b|\bxlpe\b|\bmvcc\b")
RAILWAY = re.compile(r"railway|\brly\b|\bohe\b|traction|\bmetro\b|\bmrts\b|\brrts\b")
SOLAR = re.compile(r"solar|photovoltaic|\bspv\b|\bbess\b|battery energy storage")
WATER = re.compile(
    r"water supply|drinking water|water treatment|\bwtp\b|\bstp\b|sewage|sewerage|\bjjm\b|jal jeevan|amrut"
    r"|irrigation|pipe\s?line|rising main|reservoir|\besr\b"
)
DISTRIBUTION = re.compile(
    r"distribution|under\s*-?\s*ground|\bug\b|feeder|\bht\b|\blt\b|\brmu\b|\brdss\b|reconductor"
    r"|electrification|covered conductor|\bmvcc\b"
)
# "132/33 kv", "33kv", "11 kv": a paired rating counts as its higher voltage
KV = re.compile(r"(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)\s*kv\b")


def max_kv(brief: str) -> float | None:
    volts = [float(v) for m in KV.findall(brief) for v in re.split(r"\s*/\s*", m)]
    return max(volts) if volts else None


def decide(brief: str) -> str | None:
    b = brief.lower()
    kv = max_kv(b)
    sub = bool(SUBSTATION.search(b))
    work = bool(WORK.search(b))
    # supply-only first: "supply of acsr conductor for 132 kv transmission line" is a cable tender, not transmission
    if SUPPLY.search(b) and not work:
        return "cables_conductors" if CABLE.search(b) else None
    # first match wins. railway/solar/water go before voltage: a traction substation or solar plant has a kV rating too
    if RAILWAY.search(b):
        return "railways"
    if SOLAR.search(b):
        return "solar"
    if WATER.search(b):
        return "water_distribution"
    # voltage alone counts only with work or a substation: "33 kv xlpe cable 3 core" is a cable spec, not a line
    high = kv is not None and kv > 33 and (sub or work)
    if ("opgw" in b and "supply" not in b) or "transmission" in b or high:
        return "power_transmission"
    # ponytail: a substation with no voltage counts as distribution (most DISCOM substations are 33/11 kV)
    if DISTRIBUTION.search(b) or sub or (work and kv is not None):
        return "power_distribution"
    return None


def category_point_id(ref: str, brief: str, company: str) -> str:
    # one point per tender+company (per brief when the feedback has no reference no): newer feedback replaces older
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"category:{ref or brief}:{company}"))


def add_category_feedback(brief: str, company: str, category: str, reference_no: str | None = None, note: str | None = None) -> str:
    """Embed the brief and store its correct category. Called by POST /category-feedback."""
    point_id = category_point_id(reference_no or "", brief, company)
    vec = get_dense().embed_documents([brief])[0]
    coll = ensure_collection(name=settings.category_collection)
    payload = {"reference_no": reference_no, "company": company, "brief": brief, "category": category, "note": note}
    qdrant.upsert(collection_name=coll, points=[PointStruct(id=point_id, vector={"dense": vec}, payload=payload)], wait=True)
    logger.info("category feedback upserted ref=%s company=%s category=%s point=%s", reference_no, company, category, point_id)
    return point_id


def _feedback_hits(brief: str, ref: str, company: str) -> list[dict]:
    """Category feedback for this brief: same tender first, then similar briefs. Empty on any failure."""
    try:
        coll = ensure_collection(name=settings.category_collection)
        own_id = category_point_id(ref, brief, company)
        own = qdrant.retrieve(collection_name=coll, ids=[own_id], with_payload=True)
        res = qdrant.query_points(
            collection_name=coll,
            query=get_dense().embed_query(brief),
            using="dense",
            query_filter=Filter(must=[FieldCondition(key="company", match=MatchValue(value=company))]),
            limit=5,
            score_threshold=settings.relevance_min_score,
            with_payload=True,
        )
    except Exception as e:
        logger.warning("category feedback search failed ref=%s: %s: %s", ref, type(e).__name__, e)
        return []
    hits = [{**(p.payload or {}), "score": 1.0, "same_tender": True} for p in own]
    hits += [{**(p.payload or {}), "score": float(p.score), "same_tender": False} for p in res.points if str(p.id) != own_id]
    return hits


class CategoryPick(BaseModel):
    category: Literal[tuple(EPC_CATEGORIES)]  # type: ignore[valid-type]
    reason: str = Field(description="one short sentence naming the matched keywords")


def _pick(brief: str, company: str, hits: list[dict]) -> str | None:
    options = [c for c in EPC_CATEGORIES if f"{company}_{c}" in PROMPTS]
    if not options:
        return None
    categories = "\n\n".join(f"{c}\n{EPC_CATEGORIES[c]}" for c in options)
    examples = "\n\n".join(
        f"[score {h['score']:.2f}] brief: {h.get('brief')}\ncategory: {h.get('category')}" + (f"\nnote: {h['note']}" if h.get("note") else "")
        for h in hits
    ) or "(none)"
    try:
        pick = get_llm().with_structured_output(CategoryPick).invoke(
            [
                ("system", CATEGORY_PICK.format(categories=categories)),
                ("human", f"brief: {brief}\n\nhuman category feedback on similar tenders:\n{examples}"),
            ]
        )
    except Exception as e:
        logger.error("category pick failed: %s: %s", type(e).__name__, e, exc_info=True)
        return None
    logger.info("category pick=%s reason=%s", getattr(pick, "category", None), getattr(pick, "reason", None))
    return pick.category if pick and pick.category in options else None


def categorise(state: dict[str, Any]) -> dict[str, Any]:
    extra = state.get("extra") or {}
    ref = (state.get("reference_no") or "").strip()
    company = str(state.get("company") or "").strip().lower()
    incoming = str(state.get("category") or extra.get("category") or "").strip().lower()
    brief = brief_of(extra)
    hits = _feedback_hits(brief, ref, company) if brief else []
    top = hits[0] if hits else None
    # feedback on this tender or a near-duplicate brief decides; similar feedback is only an example for the LLM
    if top and (top["same_tender"] or top["score"] >= settings.relevance_override_score):
        decided, by = top.get("category"), "feedback"
    else:
        decided, by = decide(brief), "rule"
        # a work tender is never cable supply; the dashboard sometimes sends any tender as cables_conductors
        if decided is None and WORK.search(brief.lower()) and incoming not in EPC_CATEGORIES:
            decided, by = _pick(brief, company, hits), "llm"
    if decided and f"{company}_{decided}" not in PROMPTS:
        logger.warning("categorise ref=%s: no prompt for %s_%s, keeping incoming", ref, company, decided)
        decided = None
    logger.info("categorise ref=%s incoming=%s decided=%s by=%s feedback_hits=%s", ref, incoming, decided, by, len(hits))
    # nothing decided: keep the incoming category
    return {"category": decided} if decided else {}


if __name__ == "__main__":
    cases = {
        "construction of 132/33 kv substation at xyz on turnkey basis": "power_transmission",
        "operation and maintenance of 2 nos 33kv substations": "power_distribution",
        "operation and maintenance of substation - painting of earthing": "power_distribution",
        "220 kv gis sub-station augmentation": "power_transmission",
        "laying of opgw on existing line": "power_transmission",
        "supply of opgw cable": "cables_conductors",
        "transmission line 220 kv": "power_transmission",
        "conversion of overhead network into underground cable system": "power_distribution",
        "supply and delivery of lt distribution kiosk": None,
        "supply of 1.1 kv xlpe armoured cable": "cables_conductors",
        "supply of acsr zebra conductor for 220 kv transmission line": "cables_conductors",
        "procurement of 33 kv xlpe cable for 132/33 kv substation": "cables_conductors",
        "rate contract for aaa conductor and ab cable": "cables_conductors",
        "supply of 11 kv ug cable": "cables_conductors",
        "supply and laying of 11 kv ug cable in distribution network": "power_distribution",
        "supply, erection and stringing of acsr conductor on 132 kv transmission line": "power_transmission",
        "sitc of 33 kv underground cable": "power_distribution",
        "supply of 132 kv transmission tower parts": None,
        "supply of water pipes": None,
        # work tenders: voltage now counts for lines too
        "sitc of 11 kv line with ab cable": "power_distribution",
        "s.i.t.c. of 33 kv feeder": "power_distribution",
        "sitc of 132 kv line": "power_transmission",
        "supply installation testing and commissioning of ht line": "power_distribution",
        "sitc of rmu": "power_distribution",
        "33 kv xlpe cable 3 core 300 sqmm": None,
        "design supply erection of 25 kv ohe for railway electrification": "railways",
        "epc of 5 mw ground mounted solar plant with 33 kv line": "solar",
        "construction of rural piped water supply scheme under jjm": "water_distribution",
        "construction of community hall": None,
    }
    for brief, want in cases.items():
        assert decide(brief) == want, (brief, decide(brief), want)
    print("category rules ok")
