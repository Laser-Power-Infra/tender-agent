import json
import logging

from pydantic import BaseModel, Field

from intelligence.llm import get_llm
from intelligence.state import IntelligenceState
from intelligence.predefined_checklist import get_predefined_checklist
logger = logging.getLogger(__name__)

# ponytail: single source list, prompt builds from it; add agent here → prompt auto updates
AVAILABLE_AGENTS = [
    "reverse_auction",
    "basic_details",
    "emd_agent",
    "gem_document_agent",
    "non_gem_document_agent",
    "common_document_agent",
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
    """The six agents, chosen by the planner LLM. Raises on LLM failure; caller records it."""
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
    # ponytail: inbuilt path — user_query missing, no LLM, dict import
    if not (state.get("user_query") or "").strip():
        tender_type = (state.get("tender_type") or "").strip()
        reference_no = (state.get("reference_no") or "").strip()
        checklist = get_predefined_checklist(tender_type)
        logger.info("create_checklist inbuilt ref=%s type=%r tasks=%s", reference_no, tender_type, len(checklist))
        if not checklist:
            return {"checklist": [], "errors": [{"node": "create_checklist", "error": "predefined checklist empty"}]}
        return {"checklist": checklist, "errors": []}

    parsed = state.get("parsed_request") or {}
    reference_no = (state.get("reference_no") or "").strip()
    tender_type = state.get("tender_type") or ""

    checklist: list[dict] = []
    seen: set[str] = set()
    errors: list[dict] = []

    # ponytail: checklist is now hardcoded 6 agents — 3 doc splits blank, company agent removed
    if parsed.get("requirements"):
        try:
            checklist.extend(_analytical_tasks(parsed, reference_no, checklist, seen))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            logger.error("create_checklist planning failed ref=%s error=%s", reference_no, err, exc_info=True)
            errors.append({"node": "create_checklist", "error": err})

    if not checklist:
        # fallback to hardcoded full set — checklist means which agents will run
        checklist = get_predefined_checklist(tender_type)
        if parsed.get("requirements"):
            logger.info("create_checklist fallback to predefined ref=%s tasks=%s", reference_no, len(checklist))
        else:
            logger.warning("parsed_request empty, using predefined checklist ref=%s", reference_no)

    logger.info("create_checklist done ref=%s type=%r tasks=%s", reference_no, tender_type, len(checklist))
    return {"checklist": checklist, "errors": errors}
