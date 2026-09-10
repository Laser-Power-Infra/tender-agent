import json
import logging

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from core.config import settings
from intelligence.state import IntelligenceState

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

# ponytail: single LLM instance, reuse across calls
_llm = None

def _get_llm():
    global _llm
    if _llm is not None:
        return _llm
    api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
    if not api_key:
        raise ValueError("OPENAI_API_KEY missing (set in .env)")
    # ponytail: gpt-4o-mini cheapest, upgrade when quality needs prove
    _llm = ChatOpenAI(model="gpt-4o-mini", api_key=api_key, temperature=0)
    return _llm

def create_checklist(state: IntelligenceState) -> dict:
    parsed = state.get("parsed_request") or {}
    reference_no = (state.get("reference_no") or "").strip()
    if not parsed or not parsed.get("requirements"):
        err = "parsed_request empty, cannot build checklist"
        logger.warning("%s ref=%s", err, reference_no)
        return {"checklist": [], "errors": [{"node": "create_checklist", "error": err}]}
    try:
        llm = _get_llm()
        structured = llm.with_structured_output(ChecklistPlan)
        system = _build_system_prompt()
        human = f"parsed_request: {json.dumps(parsed, ensure_ascii=False)}\nreference_no: {reference_no}"
        result: ChecklistPlan = structured.invoke([("system", system), ("human", human)])
        raw = [t.model_dump() for t in result.tasks] if result and result.tasks else []
        checklist = []
        seen = set()
        for t in raw:
            agent = (t.get("agent") or "").strip()
            if agent not in AVAILABLE_AGENTS:
                logger.warning("skip invalid agent=%r ref=%s", agent, reference_no)
                continue
            tid = (t.get("task_id") or "").strip() or f"{agent}_{len(checklist)+1}"
            # ponytail: dedup task_id O(n), list small so set is enough
            if tid in seen:
                tid = f"{tid}_{len(seen)}"
            seen.add(tid)
            checklist.append({
                "task_id": tid,
                "agent": agent,
                "description": (t.get("description") or "").strip(),
                "status": "pending",
                "result_key": None,
                "error": None,
            })
        if not checklist:
            err = "checklist empty after filtering"
            logger.warning("%s ref=%s", err, reference_no)
            return {"checklist": [], "errors": [{"node": "create_checklist", "error": err}]}
        logger.info("create_checklist done ref=%s tasks=%s", reference_no, len(checklist))
        return {"checklist": checklist}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("create_checklist failed ref=%s error=%s", reference_no, err, exc_info=True)
        return {"checklist": [], "errors": [{"node": "create_checklist", "error": err}]}
