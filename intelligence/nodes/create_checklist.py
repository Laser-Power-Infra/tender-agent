import json
import logging

from pydantic import BaseModel, Field

from intelligence.llm import get_llm
from intelligence.state import IntelligenceState
from intelligence.subagents.specialized.document_agents import (
    STATIC_QUERIES,
    agents_for_tender_type,
    section_title,
)

logger = logging.getLogger(__name__)

# ponytail: single source list, prompt builds from it; add agent here → prompt auto updates
AVAILABLE_AGENTS = [
    "company_document_finder",
    "reverse_auction",
    "eligibility",
    "important_dates",
    "financial_terms",
]

def _build_system_prompt() -> str:
    agents = "\n".join(f"- {a}" for a in AVAILABLE_AGENTS)
    return f"""You are the planning component of a multi-agent tender research system.

Based on the parsed user request, create a checklist of research tasks.

For every task:
- Select the appropriate specialized agent.
- Clearly describe what that agent must find.
- Give every task a unique task_id.
- Initially mark every task as pending.

Only select agents that are necessary to answer the user's request.

Available agents:
{agents}

Do not perform the research yourself.
Do not generate answers.
Only create the execution checklist."""

class TaskItem(BaseModel):
    task_id: str = Field(description="unique task id snake_case")
    agent: str = Field(description="agent name from available list")
    description: str = Field(description="what agent must find")

class ChecklistPlan(BaseModel):
    tasks: list[TaskItem] = Field(description="checklist of tasks")


def _analytical_tasks(parsed: dict, reference_no: str, checklist: list, seen: set) -> list[dict]:
    """The five open-ended agents, chosen by the planner LLM. Raises on LLM failure; caller records it."""
    llm = get_llm()
    structured = llm.with_structured_output(ChecklistPlan)
    system = _build_system_prompt()
    human = f"parsed_request: {json.dumps(parsed, ensure_ascii=False)}\nreference_no: {reference_no}"
    result: ChecklistPlan = structured.invoke([("system", system), ("human", human)])
    raw = [t.model_dump() for t in result.tasks] if result and result.tasks else []
    out = []
    for t in raw:
        agent = (t.get("agent") or "").strip()
        if agent not in AVAILABLE_AGENTS:
            logger.warning("skip invalid agent=%r ref=%s", agent, reference_no)
            continue
        tid = (t.get("task_id") or "").strip() or f"{agent}_{len(checklist) + len(out) + 1}"
        # ponytail: dedup task_id O(n), list small so set is enough
        if tid in seen:
            tid = f"{tid}_{len(seen)}"
        seen.add(tid)
        out.append({
            "task_id": tid,
            "agent": agent,
            "description": (t.get("description") or "").strip(),
            "status": "pending",
            "result_key": None,
            "error": None,
        })
    return out


def create_checklist(state: IntelligenceState) -> dict:
    parsed = state.get("parsed_request") or {}
    reference_no = (state.get("reference_no") or "").strip()
    tender_type = state.get("tender_type") or ""

    checklist: list[dict] = []
    seen: set[str] = set()
    errors: list[dict] = []

    # ponytail: document sections are routed by tender type, not chosen by a model. Listing 52 names in
    # the planner prompt is bloat, and "which documents does this tender need" is not a judgement call.
    for agent in agents_for_tender_type(tender_type):
        if agent in seen:
            continue
        seen.add(agent)
        documents = STATIC_QUERIES.get(agent) or []
        checklist.append({
            "task_id": agent,  # already unique and stable
            "agent": agent,
            "description": f"Determine which of the {len(documents)} documents in the {section_title(agent)} checklist this tender requires",
            "status": "pending",
            "result_key": None,
            "error": None,
        })

    # the open-ended agents still need a parsed request to plan against
    if parsed.get("requirements"):
        try:
            checklist.extend(_analytical_tasks(parsed, reference_no, checklist, seen))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            logger.error("create_checklist analytical planning failed ref=%s error=%s", reference_no, err, exc_info=True)
            errors.append({"node": "create_checklist", "error": err})
    else:
        err = "parsed_request empty, analytical agents skipped"
        logger.warning("%s ref=%s", err, reference_no)
        errors.append({"node": "create_checklist", "error": err})

    if not checklist:
        err = "checklist empty after filtering"
        logger.warning("%s ref=%s", err, reference_no)
        errors.append({"node": "create_checklist", "error": err})

    logger.info("create_checklist done ref=%s type=%r tasks=%s", reference_no, tender_type, len(checklist))
    return {"checklist": checklist, "errors": errors}
