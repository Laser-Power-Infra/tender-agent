# Intelligence v2 ReAct Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The 4 reasoning agents (reverse_auction, basic_details, emd_agent, qualification_requirement_finder) become ReAct loops that own a JEV-filtered hybrid search tool, behind `INTELLIGENCE_VERSION=v2`.

**Architecture:** New package `agents/intelligence/v2/` with a tool factory, per-agent prompts, an agent builder on `langgraph.prebuilt.create_react_agent`, and a `run_task` that returns the v1 envelope. `graph.py` picks v1 or v2 `run_task` from settings. Document agents delegate to v1.

**Tech Stack:** Python 3.12, langgraph 1.2.11 (`create_react_agent`, `GraphRecursionError`), langchain_core 1.6.1 (`@tool`, `GenericFakeChatModel`), pydantic, existing search subgraph + JEV rerank.

**Spec:** `docs/superpowers/specs/2026-11-03-intelligence-v2-react-agents-design.md`

## Global Constraints

- No new dependencies.
- `run_task` envelope keys exactly: `task_id, agent, status, result, sources, error`.
- Source dict keys exactly as v1 `execute_search`: `chunk_id, document, text, score, source_file, page`.
- `_RECURSION_LIMIT = 12`, `_TOP_K = 8`, tool text per chunk `[:1200]`, source text `[:500]`.
- Default `intelligence_version = "v1"`. Nothing in v1 changes behaviour.
- Tests need no network. Set the same env placeholders as `tests/test_status_propagation.py` before importing project modules.
- Run tests with `.venv/Scripts/python.exe -m pytest tests/test_v2_agent.py -v`.
- Commits: no model attribution lines. User's own hook adds the co-author.

## Review Focus

1. Tool called with an empty or whitespace query: returns `"no relevant chunks"` without hitting Qdrant. Test in Task 2.
2. Search subgraph returns status `failed` with `valid=[]`: tool returns `"search failed: <error>"`, not `"no relevant chunks"`. Test in Task 2.
3. Hit with no `rerank_score` (qdrant fallback path): source `score` falls back to `hit["score"]`. Test in Task 2.
4. Agent loop ends with zero tool calls (LLM answers immediately): status still `"success"`, `_finalize` still runs, sources empty. Test in Task 4.
5. Unknown agent name in v2 with `intelligence_version=v2`: delegates to v1 `run_task`, which reports `failed` as today. Test in Task 4.

---

### Task 1: Setting and graph switch

**Files:**
- Modify: `lib/core/config.py:94-112` (settings fields), `:125-140` (strip_quoted list)
- Modify: `agents/intelligence/graph.py:40-45`
- Create: `agents/intelligence/v2/__init__.py` (empty)
- Create: `agents/intelligence/v2/run_task.py` (stub for this task, filled in Task 4)
- Test: `tests/test_v2_agent.py`

**Interfaces:**
- Produces: `settings.intelligence_version: str` (`"v1"` | `"v2"`); `agents.intelligence.v2.run_task.run_task(state: dict) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_v2_agent.py  (env placeholders block at top, copied from tests/test_status_propagation.py)
def test_graph_picks_v2_run_task(monkeypatch):
    from lib.core.config import settings
    monkeypatch.setattr(settings, "intelligence_version", "v2")
    from agents.intelligence import graph as g
    from agents.intelligence.v2.run_task import run_task as v2
    compiled = g.build_intelligence_graph()
    assert compiled.get_graph().nodes["run_task"].data is v2 or compiled.builder.nodes["run_task"].runnable.func is v2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_agent.py::test_graph_picks_v2_run_task -v`
Expected: FAIL, `No module named 'agents.intelligence.v2'`

- [ ] **Step 3: Add `intelligence_version: str = "v1"` to `Settings`** under the `chat_model` field with comment `# v1 | v2 — v2 runs the 4 reasoning agents as ReAct loops (agents/intelligence/v2)`. Add `"intelligence_version"` to the `strip_quoted` field list.

- [ ] **Step 4: Create `agents/intelligence/v2/__init__.py` (empty) and `agents/intelligence/v2/run_task.py` stub**

```python
def run_task(state: dict) -> dict:  # filled in Task 4
    raise NotImplementedError
```

- [ ] **Step 5: Switch the node in `build_intelligence_graph`**

Import `settings` from `lib.core.config` and `run_task as run_task_v2` from `agents.intelligence.v2.run_task`; replace `graph.add_node("run_task", run_task)` with `graph.add_node("run_task", run_task_v2 if settings.intelligence_version == "v2" else run_task)`. Log which one at info level.

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_agent.py::test_graph_picks_v2_run_task -v`
Expected: PASS. Pick whichever assertion form matches the compiled graph's node shape and delete the other.

- [ ] **Step 7: Run existing suite for regressions**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: same pass count as before this task.

- [ ] **Step 8: Commit**

```bash
git add lib/core/config.py agents/intelligence/graph.py agents/intelligence/v2 tests/test_v2_agent.py
git commit -m "feat(intelligence): INTELLIGENCE_VERSION switch, v2 run_task stub"
```

---

### Task 2: Search tool

**Files:**
- Create: `agents/intelligence/v2/tools.py`
- Test: `tests/test_v2_agent.py`

**Interfaces:**
- Consumes: `agents.intelligence.subagents.search.graph.get_search_graph()` whose `.invoke({"query", "keywords", "reference_no"})` returns `{"valid": list[hit], "status": str, "error": str|None}`; hit = `{"id", "score", "text", "payload", "rerank_score"?}`; `_provenance(hit)` from `agents.intelligence.subagents.specialized.nodes.execute_search`.
- Produces: `make_search_tool(reference_no: str, sources: list[dict]) -> BaseTool` named `search_tender` with args `query: str, keywords: list[str] = []`, returning `str`. Appends one source dict per returned hit to `sources`.

- [ ] **Step 1: Write the failing tests**

```python
def _hit(i, text="EMD Rs 1,00,000 by DD", rerank=0.9):
    h = {"id": f"c{i}", "score": 0.4, "text": text, "payload": {"document_name": "nit.pdf", "page_no": i}}
    if rerank is not None:
        h["rerank_score"] = rerank
    return h

def _stub_search(monkeypatch, valid, status="searched", error=None, raise_=None):
    import agents.intelligence.v2.tools as t
    class G:
        def invoke(self, payload):
            if raise_: raise raise_
            return {"valid": valid, "status": status, "error": error}
    monkeypatch.setattr(t, "get_search_graph", lambda: G())

def test_tool_formats_hits_and_collects_sources(monkeypatch):
    from agents.intelligence.v2.tools import make_search_tool
    _stub_search(monkeypatch, [_hit(1), _hit(2, rerank=None)])
    sources = []
    out = make_search_tool("T1", sources).invoke({"query": "emd amount", "keywords": ["EMD"]})
    assert "[nit.pdf, page 1]" in out and "[nit.pdf, page 2]" in out and "\n---\n" in out
    assert [s["chunk_id"] for s in sources] == ["c1", "c2"]
    assert sources[0]["score"] == 0.9 and sources[1]["score"] == 0.4   # rerank_score else qdrant score
    assert set(sources[0]) == {"chunk_id", "document", "text", "score", "source_file", "page"}

def test_tool_empty_query_skips_search(monkeypatch):
    from agents.intelligence.v2.tools import make_search_tool
    _stub_search(monkeypatch, [], raise_=AssertionError("must not search"))
    assert make_search_tool("T1", []).invoke({"query": "  "}) == "no relevant chunks"

def test_tool_no_hits(monkeypatch):
    from agents.intelligence.v2.tools import make_search_tool
    _stub_search(monkeypatch, [])
    assert make_search_tool("T1", []).invoke({"query": "emd"}) == "no relevant chunks"

def test_tool_search_failed_status(monkeypatch):
    from agents.intelligence.v2.tools import make_search_tool
    _stub_search(monkeypatch, [], status="failed", error="qdrant down")
    assert make_search_tool("T1", []).invoke({"query": "emd"}).startswith("search failed: qdrant down")

def test_tool_search_raises(monkeypatch):
    from agents.intelligence.v2.tools import make_search_tool
    _stub_search(monkeypatch, [], raise_=RuntimeError("boom"))
    assert make_search_tool("T1", []).invoke({"query": "emd"}).startswith("search failed: RuntimeError: boom")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_agent.py -k tool -v`
Expected: FAIL, `No module named 'agents.intelligence.v2.tools'`

- [ ] **Step 3: Implement `make_search_tool(reference_no: str, sources: list[dict])` in `agents/intelligence/v2/tools.py`**

Module constants `_TOP_K = 8`, `_CHUNK_CHARS = 1200`, `_SOURCE_TEXT_CHARS = 500`. Inner `@tool` function `search_tender(query: str, keywords: list[str] = []) -> str` with a docstring the LLM reads: "Hybrid search inside this tender's documents. One question per call. keywords: 2-5 exact terms, acronyms or form names." Use `is_done` from `agents.intelligence.state` for the status check. Per hit block: `f"[{source_file}, page {page if page is not None else 'unspecified'}]\n{text[:_CHUNK_CHARS]}"`, joined with `"\n---\n"`. Log query, keyword count, hits kept at info.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_agent.py -k tool -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add agents/intelligence/v2/tools.py tests/test_v2_agent.py
git commit -m "feat(intelligence-v2): search_tender tool over JEV-filtered hybrid search"
```

---

### Task 3: Agent prompts and builder

**Files:**
- Create: `agents/intelligence/v2/prompts.py`
- Create: `agents/intelligence/v2/agent.py`
- Reference: `agents/intelligence/subagents/specialized/prompts.py:182-299` (v1 synthesis prompts, field meanings), `agents/intelligence/subagents/specialized/schemas.py` (output models)
- Test: `tests/test_v2_agent.py`

**Interfaces:**
- Consumes: `make_search_tool` (Task 2), `get_llm()` from `lib.core.llm`, `AGENT_OUTPUT_MODELS`.
- Produces: `AGENT_PROMPTS: dict[str, str]` keyed by the 4 agent names, each a `str.format` template with `{reference_no}` only; `V2_AGENTS: frozenset[str]`; `_RECURSION_LIMIT = 12`; `build_agent(agent: str, reference_no: str, sources: list[dict], model=None) -> CompiledGraph` (already `.with_config(recursion_limit=_RECURSION_LIMIT)`).

- [ ] **Step 1: Write the failing tests**

```python
def test_prompts_cover_reasoning_agents_only():
    from agents.intelligence.v2.prompts import AGENT_PROMPTS
    from agents.intelligence.v2.agent import V2_AGENTS, _RECURSION_LIMIT
    assert V2_AGENTS == {"reverse_auction", "basic_details", "emd_agent", "qualification_requirement_finder"}
    assert _RECURSION_LIMIT == 12
    for name, p in AGENT_PROMPTS.items():
        assert "{reference_no}" in p and "search_tender" in p and "stop" in p.lower()
        from agents.intelligence.subagents.specialized.schemas import AGENT_OUTPUT_MODELS
        for field in AGENT_OUTPUT_MODELS[name].model_fields:
            if field not in ("summary", "evidence"):
                assert field in p, f"{name} prompt missing field {field}"

def test_build_agent_runs_tool_loop(monkeypatch):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from agents.intelligence.v2 import agent as a
    _stub_search(monkeypatch, [_hit(1)])
    model = GenericFakeChatModel(messages=iter([
        AIMessage(content="", tool_calls=[{"name": "search_tender", "args": {"query": "emd amount", "keywords": ["EMD"]}, "id": "t1"}]),
        AIMessage(content="EMD is Rs 1,00,000 by DD."),
    ]))
    sources = []
    g = a.build_agent("emd_agent", "T1", sources, model=model)
    last = None
    for last in g.stream({"messages": [("human", "Analyse tender T1")]}, stream_mode="values"):
        pass
    assert len(sources) == 1
    assert sum(1 for m in last["messages"] if m.type == "tool") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_agent.py -k "prompts or build_agent" -v`
Expected: FAIL, module not found

- [ ] **Step 3: Write `agents/intelligence/v2/prompts.py`**

`AGENT_PROMPTS` with 4 entries. Each prompt, in this order: role line (`"You answer the {section} section of a tender analysis. Tender id is {reference_no}."`); field list with one-line meaning per output-model field, text ported from the matching v1 `SYNTHESIS_PROMPT`; the tool rules and stop rule verbatim from the spec's "Prompt contract" section; `"Quote nothing you did not see in a search result."`. Only `{reference_no}` is a format placeholder; escape any other braces.

- [ ] **Step 4: Implement `agents/intelligence/v2/agent.py`**

`_RECURSION_LIMIT = 12`, `V2_AGENTS = frozenset(AGENT_PROMPTS)`. `build_agent(agent, reference_no, sources, model=None)`: `model = model or get_llm()`; `create_react_agent(model, [make_search_tool(reference_no, sources)], prompt=AGENT_PROMPTS[agent].format(reference_no=reference_no))` then `.with_config(recursion_limit=_RECURSION_LIMIT)`. Raise `KeyError` for an agent outside `V2_AGENTS` (caller checks first).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_agent.py -k "prompts or build_agent" -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add agents/intelligence/v2/prompts.py agents/intelligence/v2/agent.py tests/test_v2_agent.py
git commit -m "feat(intelligence-v2): per-agent prompts and ReAct agent builder"
```

---

### Task 4: v2 run_task with finalize and recursion salvage

**Files:**
- Modify: `agents/intelligence/v2/run_task.py` (replace Task 1 stub)
- Reference: `agents/intelligence/nodes/run_task.py` (v1 envelope and checklist/errors shape)
- Test: `tests/test_v2_agent.py`

**Interfaces:**
- Consumes: `build_agent`, `V2_AGENTS`, `_RECURSION_LIMIT` (Task 3); v1 `run_task as run_task_v1`; `AGENT_OUTPUT_MODELS`; `get_llm`; `langgraph.errors.GraphRecursionError`; `DEGRADED_STATUSES`, `is_done`.
- Produces: `run_task(state: dict) -> dict` returning the same keys as v1 (`checklist`, `agent_results`, `errors`); `_finalize(messages: list, OutputModel: type[BaseModel]) -> BaseModel`; `_SALVAGE_PROMPT = "Answer now from the chunks above. Leave fields the chunks do not state empty."`.

- [ ] **Step 1: Write the failing tests**

```python
def _fake_llm(monkeypatch, result):
    import agents.intelligence.v2.run_task as r
    class S:
        calls = 0
        def invoke(self, msgs):
            S.calls += 1
            return result
    class L:
        def with_structured_output(self, model): return S()
    monkeypatch.setattr(r, "get_llm", lambda: L())
    return S

def _state(agent): return {"reference_no": "T1", "task": {"task_id": agent, "agent": agent, "status": "pending"}, "agent": agent}

def test_run_task_success_envelope(monkeypatch):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    import agents.intelligence.v2.run_task as r
    from agents.intelligence.subagents.specialized.schemas import EMDAgentOutput
    _stub_search(monkeypatch, [_hit(1)])
    model = GenericFakeChatModel(messages=iter([
        AIMessage(content="", tool_calls=[{"name": "search_tender", "args": {"query": "emd amount"}, "id": "t1"}]),
        AIMessage(content="done"),
    ]))
    monkeypatch.setattr(r, "_MODEL", model)
    S = _fake_llm(monkeypatch, EMDAgentOutput(emdAmount="Rs 1,00,000"))
    out = r.run_task(_state("emd_agent"))
    env = out["agent_results"]["emd_agent"]
    assert env["status"] == "success" and env["error"] is None
    assert env["result"]["emdAmount"] == "Rs 1,00,000" and len(env["sources"]) == 1
    assert out["checklist"][0]["status"] == "success" and out["errors"] == []
    assert S.calls == 1

def test_run_task_no_tool_calls_still_success(monkeypatch):
    # LLM answers without searching: finalize runs, sources empty, status success
    ... same shape, model = GenericFakeChatModel(messages=iter([AIMessage(content="nothing")]))
    assert env["status"] == "success" and env["sources"] == [] and S.calls == 1

def test_run_task_recursion_limit_partial(monkeypatch):
    from langchain_core.messages import AIMessage
    import itertools
    import agents.intelligence.v2.run_task as r
    from agents.intelligence.subagents.specialized.schemas import EMDAgentOutput
    _stub_search(monkeypatch, [_hit(1)])
    model = GenericFakeChatModel(messages=(AIMessage(content="", tool_calls=[{"name": "search_tender", "args": {"query": f"q{i}"}, "id": f"t{i}"}]) for i in itertools.count()))
    monkeypatch.setattr(r, "_MODEL", model)
    S = _fake_llm(monkeypatch, EMDAgentOutput(emdAmount="partial"))
    out = r.run_task(_state("emd_agent"))
    env = out["agent_results"]["emd_agent"]
    assert env["status"] == "partial" and env["error"].startswith("recursion limit 12 hit after")
    assert env["result"]["emdAmount"] == "partial" and S.calls == 1
    assert out["checklist"][0]["status"] == "success"   # partial is degraded, not failed

def test_run_task_finalize_raises_is_failed(monkeypatch):
    # _fake_llm whose invoke raises RuntimeError -> status failed, result model-shaped defaults, errors has one entry
    ...
    assert env["status"] == "failed" and env["result"]["emdAmount"] == "" and len(out["errors"]) == 1

def test_run_task_document_agent_delegates_to_v1(monkeypatch):
    import agents.intelligence.v2.run_task as r
    called = {}
    monkeypatch.setattr(r, "run_task_v1", lambda state: called.setdefault("state", state) or {"checklist": [], "agent_results": {}, "errors": []})
    monkeypatch.setattr(r, "build_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("v2 must not build")))
    r.run_task(_state("common_document_agent"))
    assert called["state"]["agent"] == "common_document_agent"

def test_run_task_unknown_agent_delegates_to_v1(monkeypatch):
    # same as above with agent "nope"; v1 owns the failure report
```

Every run_task test that builds an agent sets `monkeypatch.setattr(r, "_MODEL", model)` first; `run_task` passes `model=_MODEL` to `build_agent`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_agent.py -k run_task -v`
Expected: FAIL with `NotImplementedError`

- [ ] **Step 3: Implement `agents/intelligence/v2/run_task.py`**

```python
_SALVAGE_PROMPT = "Answer now from the chunks above. Leave fields the chunks do not state empty."
_MODEL = None  # tests inject a fake chat model here

def _finalize(messages, OutputModel):
    return get_llm().with_structured_output(OutputModel).invoke(list(messages) + [("human", _SALVAGE_PROMPT)])

def run_task(state):
    agent = (state.get("agent") or (state.get("task") or {}).get("agent") or "").strip()
    if agent not in V2_AGENTS:
        return run_task_v1(state)
    ...
```

Body: `sources = []`; `graph = build_agent(agent, reference_no, sources, model=_MODEL)`; stream with `stream_mode="values"` keeping `last`; `status = "success"`, `error = None`; `except GraphRecursionError:` set `status = "partial"`, `error = f"recursion limit {_RECURSION_LIMIT} hit after {n_tool_msgs} searches"`. Then `_finalize(last["messages"], OutputModel)` inside its own try: on exception `status = "failed"`, `error = f"{type(e).__name__}: {e}"`, `result = OutputModel().model_dump()`. Build the envelope and return `checklist`/`agent_results`/`errors` exactly as v1 `run_task` does after its `out = ...` line (copy that tail, keyed by `task_id or agent`). Log status, searches, sources at info; warn on partial.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_agent.py -v`
Expected: all PASS

- [ ] **Step 5: Run full suite**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: all PASS, no v1 test changed.

- [ ] **Step 6: Commit**

```bash
git add agents/intelligence/v2/run_task.py tests/test_v2_agent.py
git commit -m "feat(intelligence-v2): ReAct run_task with finalize and recursion salvage"
```

---

### Task 5: Live side-by-side check

**Files:**
- Modify: `.env.example` (if present) add `INTELLIGENCE_VERSION=v1` and a comment that v2 needs `RERANK_BACKEND=jev` and `TYPESAFE_API_KEY`.

- [ ] **Step 1: Pick one ingested tender** with a known EMD clause (ask the user for a `reference_no` if none is obvious from logs).

- [ ] **Step 2: Run v1** with `INTELLIGENCE_VERSION=v1`, save `final_response` to `C:\Users\BIDYUT~1\AppData\Local\Temp\claude\...\v1.json` (scratchpad).

- [ ] **Step 3: Run v2** with `INTELLIGENCE_VERSION=v2 RERANK_BACKEND=jev`, save to `v2.json`. Note search count per agent from the logs.

- [ ] **Step 4: Compare** `sections.emd_agent` and `sections.basic_details`. Report to the user: fields filled v1 vs v2, any `degraded` entries, searches per agent, wall time.

- [ ] **Step 5: Do not flip the default.** The user decides after reading the comparison.

- [ ] **Step 6: Commit**

```bash
git add .env.example
git commit -m "docs: INTELLIGENCE_VERSION in env example"
```
