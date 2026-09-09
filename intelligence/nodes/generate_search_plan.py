import logging

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from core.config import settings
from intelligence.state import IntelligenceState
from intelligence.prompts import SEARCH_PLAN_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class QueryItem(BaseModel):
    query: str = Field(description="natural question to search")
    keyword: list[str] = Field(description="2-5 keywords for hybrid/bm25 search")


class SearchPlan(BaseModel):
    items: list[QueryItem] = Field(description="array of query+keywords")


# ponytail: single LLM instance, reuse across invocations; recreate on process restart if model/key changes
_llm = None


def _get_llm():
    global _llm
    if _llm is not None:
        return _llm
    api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
    if not api_key:
        raise ValueError("OPENAI_API_KEY missing (set in .env)")
    # ponytail: gpt-4o-mini default, cheapest; upgrade to gpt-4o when quality needs prove
    _llm = ChatOpenAI(model="gpt-4o-mini", api_key=api_key, temperature=0)
    return _llm


def generate_search_plan(state: IntelligenceState) -> dict:
    reference_no = (state.get("reference_no") or "").strip()
    if not reference_no:
        err = "reference_no is required"
        logger.error(err)
        return {"status": "failed", "error": err, "search_plan": []}

    try:
        llm = _get_llm()
        structured = llm.with_structured_output(SearchPlan)
        # ponytail: structured output enforces [{query, keyword[]}], no prompt JSON hacking
        result: SearchPlan = structured.invoke(
            [
                ("system", SEARCH_PLAN_SYSTEM_PROMPT),
                ("human", f"reference_no: {reference_no}"),
            ]
        )
        items = [it.model_dump() for it in result.items] if result and result.items else []
        if not items:
            logger.warning("search plan empty reference_no=%s", reference_no)
            return {"search_plan": [], "status": "partial", "error": "empty plan"}
        logger.info("search plan generated reference_no=%s items=%s", reference_no, len(items))
        return {"search_plan": items, "status": "planned", "error": None}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("generate_search_plan failed reference_no=%s error=%s", reference_no, err, exc_info=True)
        return {"search_plan": [], "status": "failed", "error": err}
