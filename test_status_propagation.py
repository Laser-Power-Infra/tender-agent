"""Self-check: a subagent failure must survive to run_task instead of being overwritten.

Both subgraphs are unconditional linear chains, so before the reducers in intelligence/state.py the
last node's status replaced the failing node's — generate_queries "failed" became execute_search
"no_plan" became synthesize "no_results", which counted as a completed task.

Run: uv run python test_status_propagation.py
Needs no network: the empty reference_no path fails in generate_queries before any llm or qdrant call.
"""
import os

# core.config requires these; set placeholders so the check runs without a .env
for _k, _v in {
    "DATABASE_URL": "postgresql://u:p@localhost:5432/d",
    "QDRANT_URL": "http://localhost:9001",
    "QDRANT_API_KEY": "x",
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672",
    "TEMP_DIR": "./tmp",
}.items():
    os.environ.setdefault(_k, _v)

from intelligence.state import (  # noqa: E402
    DEGRADED_STATUSES,
    FAILED_STATUSES,
    is_done,
    keep_first_error,
    keep_first_failure,
)


def test_status_reducer_keeps_the_failure():
    # the exact sequence the specialized chain used to produce
    assert keep_first_failure("failed", "no_plan") == "failed"
    assert keep_first_failure(keep_first_failure("failed", "no_plan"), "no_results") == "failed"
    # normal progression still advances
    assert keep_first_failure(None, "planned") == "planned"
    assert keep_first_failure("planned", "searched") == "searched"
    assert keep_first_failure("searched", "success") == "success"
    # a node that writes nothing must not blank the key
    assert keep_first_failure("searched", None) == "searched"


def test_error_reducer_keeps_the_first_real_error():
    assert keep_first_error("boom", None) == "boom"
    assert keep_first_error(None, "boom") == "boom"
    assert keep_first_error("first", "second") == "first"
    assert keep_first_error(None, None) is None


def test_status_classification():
    assert not is_done("failed"), "a dead llm is not a completed task"
    assert not is_done("no_plan")
    # a real answer: the search ran and the tender says nothing
    for status in ("success", "searched", "no_results", "no_valid", "no_hits"):
        assert is_done(status), status
    # degraded finished, but not by the intended path
    for status in DEGRADED_STATUSES:
        assert is_done(status), status
    assert not (FAILED_STATUSES & DEGRADED_STATUSES), "a status cannot be both"


def test_failure_survives_the_specialized_chain():
    """The end-to-end guarantee, through the real compiled graph."""
    from intelligence.subagents.specialized.graph import get_specialized_graph

    out = get_specialized_graph().invoke(
        {"reference_no": "", "task": {"task_id": "t1", "agent": "emd_agent"}, "agent": "emd_agent"}
    )
    assert out["status"] == "failed", f"expected the generate_queries failure to survive, got {out['status']!r}"
    assert "reference_no" in (out.get("error") or ""), out.get("error")


def test_run_task_records_the_failure():
    from intelligence.nodes.run_task import run_task

    out = run_task({"reference_no": "", "task": {"task_id": "t1", "agent": "emd_agent"}, "agent": "emd_agent"})
    item = out["checklist"][0]
    assert item["status"] == "failed", f"task reported {item['status']!r} for a failed subagent"
    assert item["error"], "the real cause must reach the checklist, not None"
    assert out["errors"], out
    envelope = out["agent_results"]["t1"]
    assert envelope["status"] == "failed", envelope
    assert envelope["error"], envelope


def test_final_response_lists_it_as_failed():
    from intelligence.nodes.run_task import run_task
    from intelligence.nodes.synthesize_final_result import synthesize_final_result

    task = run_task({"reference_no": "", "task": {"task_id": "t1", "agent": "emd_agent"}, "agent": "emd_agent"})
    final = synthesize_final_result({"reference_no": "R1", "agent_results": task["agent_results"]})["final_response"]
    assert final["failed"] == ["emd_agent"], final
    assert final["degraded"] == [], final
    # the section still exists with its declared fields, so nothing is lost
    assert "emdAmount" in final["sections"]["emd_agent"], final["sections"]


if __name__ == "__main__":
    test_status_reducer_keeps_the_failure()
    test_error_reducer_keeps_the_first_real_error()
    test_status_classification()
    test_failure_survives_the_specialized_chain()
    test_run_task_records_the_failure()
    test_final_response_lists_it_as_failed()
    print("status propagation self-check passed")
