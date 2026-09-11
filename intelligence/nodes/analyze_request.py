import logging

from pydantic import BaseModel, Field

from intelligence.llm import get_llm
from intelligence.state import IntelligenceState

logger = logging.getLogger(__name__)

ANALYZE_REQUEST_SYSTEM_PROMPT = """You are the request analysis component of a tender research system.

Your job is to understand the user's request and convert it into a structured representation.

Extract:
1. The user's main intent.
2. The tender/reference number.
3. The specific information the user is requesting.
4. Any explicit constraints.

Do not perform document retrieval.
Do not answer the user's question.
Do not invent information.

Return only the required structured output."""

class Requirement(BaseModel):
    type: str = Field(description="requirement type e.g. required_documents, reverse_auction")
    description: str = Field(description="what the requirement asks for")

class ParsedRequest(BaseModel):
    intent: str = Field(description="main intent e.g. tender_requirements")
    reference_no: str = Field(description="tender/reference number")
    requirements: list[Requirement] = Field(description="specific information requested")


def analyze_request(state: IntelligenceState) -> dict:
    user_query = (state.get("user_query") or "").strip()
    reference_no = (state.get("reference_no") or "").strip()
    if not user_query:
        err = "user_query is required"
        logger.error(err)
        return {"parsed_request": {}, "errors": [{"node": "analyze_request", "error": err}]}
    try:
        llm = get_llm()
        structured = llm.with_structured_output(ParsedRequest)
        # ponytail: structured output enforces schema, no JSON prompt hacking
        result: ParsedRequest = structured.invoke(
            [
                ("system", ANALYZE_REQUEST_SYSTEM_PROMPT),
                ("human", f"user_query: {user_query}\nreference_no: {reference_no}"),
            ]
        )
        parsed = result.model_dump() if result else {}
        # prefer explicit reference_no from state if LLM left blank
        if not (parsed.get("reference_no") or "").strip() and reference_no:
            parsed["reference_no"] = reference_no
        logger.info("analyze_request done intent=%s reqs=%s ref=%s", parsed.get("intent"), len(parsed.get("requirements") or []), parsed.get("reference_no"))
        return {"parsed_request": parsed}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("analyze_request failed error=%s", err, exc_info=True)
        return {"parsed_request": {}, "errors": [{"node": "analyze_request", "error": err}]}
