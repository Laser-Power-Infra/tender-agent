"""Predefined checklist for missing user_query — no LLM.

Single source reuse: same agents_for_tender_type + STATIC_QUERIES as
create_checklist deterministic part, but isolated for inbuilt path.
"""

from intelligence.subagents.specialized.document_agents import (
    STATIC_QUERIES,
    agents_for_tender_type,
    section_title,
)


def get_predefined_checklist(tender_type: str = "") -> list[dict]:
    seen: set[str] = set()
    checklist: list[dict] = []
    for agent in agents_for_tender_type(tender_type):
        if agent in seen:
            continue
        seen.add(agent)
        documents = STATIC_QUERIES.get(agent) or []
        checklist.append(
            {
                "task_id": agent,
                "agent": agent,
                "description": f"Determine which of the {len(documents)} documents in the {section_title(agent)} checklist this tender requires",
                "status": "pending",
                "result_key": None,
                "error": None,
            }
        )
    return checklist
