import logging

from intelligence.llm import get_llm
from intelligence.subagents.specialized.document_agents import STATIC_QUERIES
from intelligence.subagents.specialized.prompts import SYNTHESIS_PROMPT
from intelligence.subagents.specialized.schemas import AGENT_OUTPUT_MODELS, SynthesisResult
from intelligence.subagents.specialized.state import SpecializedState

logger = logging.getLogger(__name__)

# ponytail: per document, matching execute_search._HITS_PER_DOC. 25 docs x 2 x 700 ~= 35k chars ~= 9k
# tokens — the old global 21 hits / 8000 chars could not represent a section at all.
_HITS_PER_DOC = 2
_CHARS_PER_HIT = 700
_MAX_CONTEXT_CHARS = 40000

_NO_CHUNKS = "(no chunks retrieved)"


def _build_context(agent: str, search_results: list[dict]) -> str:
    """Group evidence by checklist document, in checklist order.

    Every checklist document appears, with or without hits. That is what makes the prompt's "output
    exactly N objects" achievable — an absent document has no slot to answer "Unclear" in.
    Non-document agents have no checklist, so they group by query instead. Same code path.
    """
    by_key: dict[str, list[str]] = {}
    for result in search_results:
        hit = result.get("hit") or {}
        text = (hit.get("text") or "").strip()
        if not text:
            continue
        key = result.get("document") or result.get("query") or ""
        block = by_key.setdefault(key, [])
        if len(block) >= _HITS_PER_DOC:
            continue
        payload = hit.get("payload") or {}
        source_file = payload.get("document_name") or payload.get("documentName") or "unknown file"
        page = payload.get("page_no", payload.get("pageNo"))
        block.append(f"[source_file: {source_file}, page: {page if page is not None else 'unspecified'}]\n{text[:_CHARS_PER_HIT]}")

    checklist = [q["document"] for q in STATIC_QUERIES.get(agent, [])]
    keys = checklist or list(by_key)
    blocks = [f"## document: {k}\n" + ("\n\n".join(by_key[k]) if by_key.get(k) else _NO_CHUNKS) for k in keys]
    return "\n\n---\n\n".join(blocks)[:_MAX_CONTEXT_CHARS]


def synthesize(state: SpecializedState) -> dict:
    task = state.get("task") or {}
    agent = (state.get("agent") or task.get("agent") or "").strip()
    search_results: list[dict] = state.get("search_results") or []
    reference_no = (state.get("reference_no") or "").strip()

    # ponytail: a checklist agent with zero hits still owes one "Unclear" row per document, so it must
    # reach the model. Only the open-ended agents can short-circuit to an empty envelope.
    if not search_results and agent not in STATIC_QUERIES:
        logger.info("synthesize no results agent=%s ref=%s", agent, reference_no)
        return {
            "result": {"summary": "No relevant context found", "findings": [], "evidence": [], "documents": []},
            "status": "no_results",
            "error": None,
        }

    context = _build_context(agent, search_results)
    task_desc = task.get("description") or task.get("task_id") or agent
    # ponytail: per-agent synthesis prompt dict, agent type -> proper prompt
    raw_prompt = SYNTHESIS_PROMPT.get(agent) or SYNTHESIS_PROMPT.get("company_document_finder") or ""
    if not raw_prompt:
        raw_prompt = "You are {agent} synthesis. Combine context for task: {task_description}."
    if "{agent}" in raw_prompt or "{task_description}" in raw_prompt:
        try:
            sys_prompt = raw_prompt.format(agent=agent or "specialized", task_description=task_desc)
        except Exception:
            sys_prompt = raw_prompt
    else:
        sys_prompt = raw_prompt

    # ponytail: per-agent output model, agent type -> proper schema
    OutputModel = AGENT_OUTPUT_MODELS.get(agent, SynthesisResult)
    try:
        llm = get_llm()
        structured = llm.with_structured_output(OutputModel)
        out = structured.invoke(
            [
                ("system", sys_prompt),
                ("human", f"reference_no: {reference_no}\ncontext:\n{context}"),
            ]
        )
        result = out.model_dump() if out else {}
        logger.info("synthesize done agent=%s model=%s ref=%s chars=%s", agent, OutputModel.__name__, reference_no, len(context))
        return {"result": result, "status": "success", "error": None}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("synthesize failed agent=%s ref=%s error=%s", agent, reference_no, err, exc_info=True)
        # ponytail: fallback aggregate without LLM
        texts = [(r.get("hit") or {}).get("text") or "" for r in search_results[:3]]
        texts = [t.strip()[:500] for t in texts if t.strip()]
        fallback = {"summary": texts[0] if texts else "", "findings": texts, "evidence": texts, "documents": []}
        return {"result": fallback, "status": "fallback", "error": err}
