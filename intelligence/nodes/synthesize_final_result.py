import logging

from pydantic import ValidationError

from intelligence.state import DEGRADED_STATUSES, IntelligenceState, is_done
from intelligence.subagents.specialized.schemas import AGENT_OUTPUT_MODELS, SynthesisResult

logger = logging.getLogger(__name__)


def _coerce(agent: str, result: dict | None) -> dict:
    """Normalize one agent result to the model that agent declares.

    The subagent returns the generic SynthesisResult shape on zero hits and on llm failure
    (specialized/nodes/synthesize.py:59, :98) whatever agent ran, so a failed emd_agent arrives
    with no emdAmount key at all. Validating through the declared model fills every declared
    field with its default, so a section is never missing a field it promises.
    """
    model = AGENT_OUTPUT_MODELS.get(agent, SynthesisResult)
    data = dict(result or {})
    try:
        return model.model_validate(data).model_dump()
    except ValidationError as e:
        # the foreign shape collides on some fields but not all — e.g. the generic result carries
        # evidence as a list where this model wants an Evidence object. Drop only what does not
        # fit and revalidate, so the declared defaults fill those slots instead of losing the
        # whole model. model_construct is not an option: it dumps {} when a required field is
        # absent.
        bad = {str(err["loc"][0]) for err in e.errors() if err.get("loc")}
        kept = {k: v for k, v in data.items() if k not in bad}
        logger.warning("result does not fit %s agent=%s dropped=%s", model.__name__, agent, sorted(bad))
        try:
            return model.model_validate(kept).model_dump()
        except ValidationError as e2:
            logger.error("cannot coerce agent=%s to %s, keeping raw: %s", agent, model.__name__, e2)
            return data


def synthesize_final_result(state: IntelligenceState) -> dict:
    """Merge every agent result into one response. No llm.

    ponytail: was a second llm call with `sections: dict` as its output schema — an untyped dict
    is JSON Schema `{"type": "object"}` with no properties, so the model invented its own field
    names instead of keeping each agent's. Agents already return typed results; this just collects
    them.
    """
    reference_no = (state.get("reference_no") or "").strip()
    agent_results = state.get("agent_results") or {}

    if not agent_results:
        err = "agent_results empty, nothing to merge"
        logger.warning("%s ref=%s", err, reference_no)
        return {
            "final_response": {"tender_id": reference_no, "sections": {}, "failed": [], "degraded": []},
            "errors": [{"node": "synthesize_final_result", "error": err}],
        }

    sections: dict = {}
    failed: list[str] = []
    degraded: list[str] = []
    for task_id, envelope in agent_results.items():
        envelope = envelope or {}
        # run_task keys by task_id on success and by agent on the exception path, so read the
        # agent off the envelope and fall back to the key
        agent = envelope.get("agent") or task_id
        # two tasks for one agent keep both, second one suffixed
        key = agent if agent not in sections else f"{agent}#{task_id}"
        sections[key] = _coerce(agent, envelope.get("result"))
        status = envelope.get("status")
        if not is_done(status):
            failed.append(key)
        elif status in DEGRADED_STATUSES:
            # answered, but the llm or the reranker fell back — the caller must not read this as
            # a clean extraction
            degraded.append(key)

    final = {"tender_id": reference_no, "sections": sections, "failed": failed, "degraded": degraded}
    logger.info("final result merged ref=%s sections=%s failed=%s degraded=%s", reference_no, len(sections), len(failed), len(degraded))
    return {"final_response": final}
