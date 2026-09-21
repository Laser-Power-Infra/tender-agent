"""Self-check for the intelligence fan-out: reducers merge parallel writes, fan_out_tasks routes correctly.

Run: python test_fan_out.py
Stubs langgraph so it needs no installed deps.
"""
import sys
import types


def _stub_langgraph():
    if "langgraph" in sys.modules:
        return
    lg = types.ModuleType("langgraph")
    graph_mod = types.ModuleType("langgraph.graph")
    types_mod = types.ModuleType("langgraph.types")

    class Send:
        def __init__(self, node, arg):
            self.node = node
            self.arg = arg

    graph_mod.START = "__start__"
    graph_mod.END = "__end__"
    graph_mod.StateGraph = object
    types_mod.Send = Send
    lg.graph = graph_mod
    lg.types = types_mod
    sys.modules.update({"langgraph": lg, "langgraph.graph": graph_mod, "langgraph.types": types_mod})
    # the node imports pull in langchain/openai; the fan-out logic does not need them
    for name in (
        "intelligence.nodes.analyze_request",
        "intelligence.nodes.create_checklist",
        "intelligence.nodes.run_task",
        "intelligence.nodes.synthesize_final_result",
    ):
        mod = types.ModuleType(name)
        setattr(mod, name.rsplit(".", 1)[1], lambda state: {})
        sys.modules[name] = mod


_stub_langgraph()
from intelligence.graph import fan_out_tasks  # noqa: E402
from intelligence.state import merge_agent_results, merge_checklist  # noqa: E402


def test_fan_out_sends_one_per_pending_task():
    state = {
        "reference_no": "T123",
        "checklist": [
            {"task_id": "a", "agent": "eligibility", "status": "pending"},
            {"task_id": "b", "agent": "important_dates", "status": "pending"},
            {"task_id": "c", "agent": "eligibility", "status": "success"},
        ],
    }
    sends = fan_out_tasks(state)
    assert len(sends) == 2, sends
    assert [s.node for s in sends] == ["run_task", "run_task"]
    assert [s.arg["task"]["task_id"] for s in sends] == ["a", "b"]
    assert all(s.arg["reference_no"] == "T123" for s in sends)


def test_empty_checklist_skips_to_synthesis():
    assert fan_out_tasks({"checklist": []}) == "synthesize_final_result"
    assert fan_out_tasks({}) == "synthesize_final_result"
    assert fan_out_tasks({"checklist": [{"task_id": "a", "status": "success"}]}) == "synthesize_final_result"


def test_agent_results_merge_keeps_every_parallel_write():
    left = merge_agent_results({}, {"a": {"status": "success"}})
    both = merge_agent_results(left, {"b": {"status": "failed"}})
    assert set(both) == {"a", "b"}, both
    # two tasks for the same agent keep separate task_id keys, neither is lost
    same_agent = merge_agent_results({"elig_1": {"agent": "eligibility"}}, {"elig_2": {"agent": "eligibility"}})
    assert len(same_agent) == 2, same_agent


def test_checklist_merge_replaces_by_task_id_and_keeps_order():
    base = [
        {"task_id": "a", "status": "pending"},
        {"task_id": "b", "status": "pending"},
    ]
    # b finishes before a — order must still be a, b
    after_b = merge_checklist(base, [{"task_id": "b", "status": "success"}])
    after_a = merge_checklist(after_b, [{"task_id": "a", "status": "failed"}])
    assert [i["task_id"] for i in after_a] == ["a", "b"], after_a
    assert [i["status"] for i in after_a] == ["failed", "success"], after_a
    assert len(after_a) == 2, "an update must replace, never append a duplicate"


def test_checklist_merge_appends_unknown_task():
    out = merge_checklist([{"task_id": "a", "status": "pending"}], [{"task_id": "z", "status": "success"}])
    assert [i["task_id"] for i in out] == ["a", "z"], out


if __name__ == "__main__":
    test_fan_out_sends_one_per_pending_task()
    test_empty_checklist_skips_to_synthesis()
    test_agent_results_merge_keeps_every_parallel_write()
    test_checklist_merge_replaces_by_task_id_and_keeps_order()
    test_checklist_merge_appends_unknown_task()
    print("fan-out self-check passed")
