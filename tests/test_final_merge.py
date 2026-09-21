"""Self-check for synthesize_final_result: merge only, every declared field survives.

Run: uv run python test_final_merge.py
"""
from intelligence.nodes.synthesize_final_result import synthesize_final_result


def _envelope(agent, result, status="success", task_id=None, sources_text="RAWCHUNK"):
    return {
        "task_id": task_id or agent,
        "agent": agent,
        "status": status,
        "result": result,
        "sources": [{"chunk_id": "c1", "text": sources_text, "score": 1.0}] * 21,
        "error": None if status == "success" else "boom",
    }


def _merge(agent_results, ref="NIT/2024/0142"):
    return synthesize_final_result({"reference_no": ref, "agent_results": agent_results})["final_response"]


def test_basic_details_keeps_its_own_fields():
    # the regression this whole node was rewritten for: the llm used to rename these
    result = {
        "title": "Supply of laser units",
        "reference_no": "NIT/2024/0142",
        "organization": "WBSEDCL",
        "eligibility": ["3 years turnover"],
        "important_dates": ["bid close 2024-04-01"],
        "summary": "supply tender",
        "evidence": {"output": "clause 4.1", "found_document": "nit.pdf", "documentId": "d1", "pageNo": 7},
    }
    out = _merge({"basic_details": _envelope("basic_details", result)})
    section = out["sections"]["basic_details"]
    assert set(section) == set(result), section
    assert section["title"] == "Supply of laser units", section
    assert section["eligibility"] == ["3 years turnover"], section
    assert section["evidence"]["pageNo"] == 7, section


def test_zero_hit_agent_still_gets_its_declared_fields():
    # specialized/nodes/synthesize.py:59 returns the generic shape whatever agent ran,
    # so emd_agent arrives with no emdAmount at all — coercion must fill it, not drop it
    zero_hit = {"summary": "No relevant context found", "findings": [], "evidence": [], "documents": []}
    out = _merge({"emd_agent": _envelope("emd_agent", zero_hit)})
    section = out["sections"]["emd_agent"]
    assert section["emdAmount"] == "", section
    assert section["emdPaymentMode"] == "", section
    assert section["emdExemption"] == [], section
    assert section["emdValidity"] == "", section
    assert section["summary"] == "No relevant context found", section
    assert section["evidence"]["output"] == "", section


def test_zero_hit_document_agent_gets_an_empty_results_list():
    # document_finder's declared field is `results`, absent from the generic zero-hit shape.
    # It must come back as [] — an empty section, not a section missing the field.
    zero_hit = {"summary": "No relevant context found", "findings": [], "evidence": [], "documents": []}
    out = _merge({"document_finder": _envelope("document_finder", zero_hit)})
    assert out["sections"]["document_finder"] == {"results": []}, out["sections"]


def test_unclear_rows_are_kept():
    rows = [
        {"document": "PAN Card", "required": "Required", "found": "nit.pdf, page 2", "evidence": "listed", "confidence": "High"},
        {"document": "GST LUT", "required": "Unclear", "found": "Not found", "evidence": "", "confidence": "Low"},
    ]
    out = _merge({"df_1": _envelope("document_finder", {"results": rows}, task_id="df_1")})
    kept = out["sections"]["document_finder"]["results"]
    assert [r["document"] for r in kept] == ["PAN Card", "GST LUT"], kept
    assert "unclear_count" not in out["sections"]["document_finder"], "rows are merged now, not summarized away"


def test_sources_never_reach_the_response():
    out = _merge({"basic_details": _envelope("basic_details", {"title": "t"}, sources_text="RAWCHUNK")})
    assert "RAWCHUNK" not in repr(out), out
    assert "sources" not in repr(out), out


def test_failed_agent_is_listed_and_still_gets_a_section():
    out = _merge({"ra": _envelope("reverse_auction", {}, status="failed")})
    assert out["failed"] == ["reverse_auction"], out
    assert out["sections"]["reverse_auction"]["applicable"] is False, out


def test_no_results_is_not_a_failure():
    out = _merge({"emd_agent": _envelope("emd_agent", {}, status="no_results")})
    assert out["failed"] == [], out
    assert out["degraded"] == [], out


def test_degraded_is_neither_success_nor_failure():
    # synthesize.py returns "fallback" when its llm call died — it produced something, but the
    # caller must not read it as a clean extraction
    out = _merge({"emd_agent": _envelope("emd_agent", {}, status="fallback")})
    assert out["failed"] == [], out
    assert out["degraded"] == ["emd_agent"], out
    # and the section is still there, so nothing is lost
    assert "emdAmount" in out["sections"]["emd_agent"], out


def test_two_tasks_one_agent_keep_both():
    out = _merge({
        "a_1": _envelope("common_document_agent", {"documents": ["PAN"]}, task_id="a_1"),
        "a_2": _envelope("common_document_agent", {"documents": ["GST"]}, task_id="a_2"),
    })
    assert out["sections"]["common_document_agent"]["documents"] == ["PAN"], out
    assert out["sections"]["common_document_agent#a_2"]["documents"] == ["GST"], out


def test_unregistered_agent_falls_back_to_synthesis_result():
    out = _merge({"common.works_construction": _envelope("common.works_construction", {"summary": "s"})})
    section = out["sections"]["common.works_construction"]
    assert set(section) == {"summary", "findings", "evidence", "documents"}, section


def test_empty_agent_results():
    state = synthesize_final_result({"reference_no": "R1", "agent_results": {}})
    assert state["final_response"] == {"tender_id": "R1", "sections": {}, "failed": [], "degraded": []}, state
    assert state["errors"][0]["node"] == "synthesize_final_result", state


if __name__ == "__main__":
    test_basic_details_keeps_its_own_fields()
    test_zero_hit_agent_still_gets_its_declared_fields()
    test_zero_hit_document_agent_gets_an_empty_results_list()
    test_unclear_rows_are_kept()
    test_sources_never_reach_the_response()
    test_failed_agent_is_listed_and_still_gets_a_section()
    test_no_results_is_not_a_failure()
    test_degraded_is_neither_success_nor_failure()
    test_two_tasks_one_agent_keep_both()
    test_unregistered_agent_falls_back_to_synthesis_result()
    test_empty_agent_results()
    print("final merge self-check passed")
