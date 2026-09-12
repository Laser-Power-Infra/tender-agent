"""Hardcoded checklist — which agents will run. Tender_type controls doc agents."""
import logging

logger = logging.getLogger(__name__)

_BASE_AGENTS = [
    "reverse_auction",
    "basic_details",
    "emd_agent",
]


def _doc_agents(tender_type: str = "") -> list[str]:
    """Bucket agent for a known type, plus common. Unknown type gets common only.

    ponytail: was `== "GEM" else non_gem`, which asserted every unrecognized tender was non-GeM and
    asked it 76 non-GeM-only document questions. worker/job.py normalizes to "gem"/"non_gem"/"" and
    documents "" as unknown; common is valid for either bucket, so an unknown type costs coverage
    rather than inventing a fact about the tender.
    """
    t = (tender_type or "").strip().lower()
    if t == "gem":
        return ["gem_document_agent", "common_document_agent"]
    if t == "non_gem":
        return ["non_gem_document_agent", "common_document_agent"]
    logger.warning("tender_type=%r unknown, running common documents only", tender_type)
    return ["common_document_agent"]


def get_predefined_checklist(tender_type: str = "") -> list[dict]:
    agents = _BASE_AGENTS + _doc_agents(tender_type)
    return [
        {
            "task_id": agent,
            "agent": agent,
            "description": f"Run {agent}",
            "status": "pending",
            "result_key": None,
            "error": None,
        }
        for agent in agents
    ]
