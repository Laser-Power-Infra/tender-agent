import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ponytail: the rules are keyword + voltage checks, so plain code. The LLM version returned null even for
# "132/33 kv substation" and "distribution transformer". Add an LLM fallback only for briefs no rule can read.
SUBSTATION = re.compile(r"sub[\s-]?stations?\b|\bs/s\b")
# "132/33 kv", "33kv", "11 kv": a paired rating counts as its higher voltage
KV = re.compile(r"(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)\s*kv\b")


def max_kv(brief: str) -> float | None:
    volts = [float(v) for m in KV.findall(brief) for v in re.split(r"\s*/\s*", m)]
    return max(volts) if volts else None


def decide(brief: str) -> str | None:
    b = brief.lower()
    kv = max_kv(b)
    sub = bool(SUBSTATION.search(b))
    # first match wins: transmission rules, then distribution rules
    if ("opgw" in b and "supply" not in b) or "transmission" in b or (sub and kv is not None and kv > 33):
        return "power_transmission"
    # ponytail: a substation with no voltage counts as distribution (most DISCOM substations are 33/11 kV)
    if "distribution" in b or ("under" in b and "ground" in b) or sub:
        return "power_distribution"
    return None


def categorise(state: dict[str, Any]) -> dict[str, Any]:
    extra = state.get("extra") or {}
    incoming = str(state.get("category") or extra.get("category") or "").strip().lower()
    brief = str(extra.get("tenderbrief") or extra.get("tenderBrief") or "")
    decided = decide(brief)
    logger.info("categorise incoming=%s decided=%s", incoming, decided)
    # no rule matched: keep the incoming category
    return {"category": decided} if decided else {}


if __name__ == "__main__":
    cases = {
        "construction of 132/33 kv substation at xyz on turnkey basis": "power_transmission",
        "operation and maintenance of 2 nos 33kv substations": "power_distribution",
        "operation and maintenance of substation - painting of earthing": "power_distribution",
        "220 kv gis sub-station augmentation": "power_transmission",
        "laying of opgw on existing line": "power_transmission",
        "supply of opgw cable": None,
        "transmission line 220 kv": "power_transmission",
        "conversion of overhead network into underground cable system": "power_distribution",
        "supply and delivery of lt distribution kiosk": "power_distribution",
        "supply of 1.1 kv xlpe armoured cable": None,
        "supply of water pipes": None,
    }
    for brief, want in cases.items():
        assert decide(brief) == want, (brief, decide(brief), want)
    assert categorise({"category": "cables_conductors", "extra": {"tenderbrief": "supply of acsr conductor"}}) == {}
    print("category rules ok")
