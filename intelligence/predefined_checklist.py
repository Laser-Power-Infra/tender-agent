"""Hardcoded checklist — which agents will run. Tender_type controls doc agents."""

_BASE_AGENTS = [
    "reverse_auction",
    "basic_details",
    "emd_agent",
]


def _doc_agents(tender_type: str = "") -> list[str]:
    # ponytail: GEM vs NON_GEM only, common always
    if (tender_type or "").strip().upper() == "GEM":
        return ["gem_document_agent", "common_document_agent"]
    return ["non_gem_document_agent", "common_document_agent"]


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
