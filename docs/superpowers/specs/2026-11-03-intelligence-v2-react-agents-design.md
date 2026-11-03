# Intelligence v2: ReAct agents with a JEV-filtered search tool

Date: 2026-11-03. Status: approved in chat, pending spec review.

## Problem

v1 specialized subgraph is `generate_queries -> execute_search -> synthesize`. Queries are fixed up front, every
query runs once, the LLM answers from whatever was pre-retrieved. When the first queries miss, the answer is wrong
and nothing retries. Users report the AI analysis "not working out" for the reasoning sections (EMD, basic details,
qualification, reverse auction).

## Goal

Each reasoning agent is an LLM agent that owns a search tool, decides its own queries, reads results, searches
again until its output schema has evidence, then answers in the existing schema. Nothing outside the agent changes.

## Decisions

1. **JEV is relevance only, never chat.** The tool runs Qdrant hybrid search then JEV `system_one` marks each chunk
   relevant or irrelevant. Reasoning LLM stays `settings.chat_model` via `lib/core/llm.get_llm`.
2. **Scope: the 4 reasoning agents.** `reverse_auction`, `basic_details`, `emd_agent`,
   `qualification_requirement_finder`. Document agents (`gem_document_agent`, `non_gem_document_agent`,
   `common_document_agent`) keep v1: their checklist is 49/62/90 fixed documents with one fixed yes/no question each.
   A ReAct loop there is 90+ LLM steps per tender for no reasoning gain.
3. **Prebuilt ReAct.** `langgraph.prebuilt.create_react_agent(model, tools, prompt)`. Installed langgraph 1.2.11
   exposes it. No new dependency. No `response_format`: the final structured answer is one explicit
   `with_structured_output` call over the agent's messages, so the normal end and the recursion-limit salvage share
   one code path (`_finalize`).
4. **v1 stays. v2 behind a setting.** `settings.intelligence_version` = `"v1"` (default) or `"v2"`. Worker, queue,
   checklist, fan-out, final synthesis, webhook untouched.
5. **Output contract unchanged.** Same `AGENT_OUTPUT_MODELS` schema per agent, same `run_task` envelope
   (`task_id, agent, status, result, sources, error`), same `final_response`.
6. **Relevance backend is config.** The tool calls the existing search subgraph (`hybrid_search -> rerank`), which
   reads `settings.rerank_backend`. v2 deployment sets `RERANK_BACKEND=jev`. The tool does not force it.

## Architecture

```
worker -> predefined checklist -> fan_out_tasks -> run_task (v1 or v2) -> synthesize_final_result -> webhook
                                                        |
                                 v2, reasoning agent:   |   v2, document agent: v1 run_task unchanged
                                                        v
                     create_react_agent(llm, [search_tender], prompt[agent])
                                                        |
                        loop: LLM -> search_tender(query, keywords) -> search subgraph -> JEV filter -> chunks -> LLM
                                                        |
                 normal end -> _finalize -> "success"  |  GraphRecursionError -> _finalize -> "partial"
```

## Components

New package `agents/intelligence/v2/`:

| File | Owns |
|---|---|
| `tools.py` | `make_search_tool(reference_no, sources)` -> `@tool search_tender(query, keywords=[])`. Invokes `get_search_graph()` with `{query, keywords, reference_no}`. Takes top `_TOP_K=8` of `valid`, appends a source dict per hit to `sources` (same shape as v1 `execute_search`: chunk_id, document="", text[:500], score, source_file, page), returns `"[file, page <n>]\n<text[:1200]>"` blocks joined by `---`. Empty -> `"no relevant chunks"`. Search failure -> `"search failed: <err>"` as a string, never raised. |
| `prompts.py` | `AGENT_PROMPTS: dict[str, str]` for the 4 agents. Each: role, the fields of its output model with one line of meaning each (ported from v1 `SYNTHESIS_PROMPT`), tool rules, stop rule. |
| `agent.py` | `build_agent(agent, reference_no, sources, model=None)` -> compiled react agent with `recursion_limit=_RECURSION_LIMIT` (12, i.e. about 5 search rounds). `model` defaults to `get_llm()`; tests pass a fake. `V2_AGENTS = frozenset(AGENT_PROMPTS)`. |
| `run_task.py` | `run_task(state)`. Agent not in `V2_AGENTS` -> delegate to v1 `agents.intelligence.nodes.run_task.run_task`. Else build agent, stream with `stream_mode="values"` keeping the last state, `_finalize(messages, OutputModel)` for the structured answer, produce envelope. |

Changed:

| File | Change |
|---|---|
| `lib/core/config.py` | `intelligence_version: str = "v1"` plus its name in the logged-settings list. |
| `agents/intelligence/graph.py` | `add_node("run_task", run_task_v2 if settings.intelligence_version == "v2" else run_task)`. |

Reused as is: `predefined_checklist`, `fan_out_tasks`, `synthesize_final_result`, `AGENT_OUTPUT_MODELS`,
`get_search_graph` (hybrid_search + rerank), `get_llm`, `get_jev`, `DEGRADED_STATUSES`, `is_done`.

## Prompt contract (every reasoning agent)

- "You answer one section of a tender analysis. Tender id is {reference_no}."
- Required fields listed with meaning. "A field is answered when a chunk states it. Quote nothing you did not see."
- Tool rules: one question per `search_tender` call, 3 to 12 words, tender vocabulary; pass 2 to 5 `keywords`
  (acronyms, form names, clause words). After a miss, reword once with different terms. Never repeat a query.
- Stop rule: "Stop and answer when every field has evidence, or every missing field was searched twice. Leave a
  field empty when the tender does not state it. Fill `evidence` from the chunk that answered the most fields."
- Hard limit is the graph's `recursion_limit`, not the prompt.

## Data flow, one task

1. `fan_out_tasks` sends `{reference_no, task, agent}` to `run_task` exactly as today.
2. v2 `run_task`: agent in `V2_AGENTS`? no -> v1. yes -> `sources = []`, `agent_graph = build_agent(...)`.
3. `for state in agent_graph.stream({"messages": [("human", "Analyse tender {reference_no}")]}, stream_mode="values"): last = state`.
4. Normal end: `_finalize(last["messages"], OutputModel)` = one
   `get_llm().with_structured_output(OutputModel).invoke(messages + [("human", "Answer now from the chunks above. Leave fields the chunks do not state empty.")])`.
   Envelope status `"success"`, result = `model_dump()`, sources = collected list, error None.
5. Tool calls that return `"no relevant chunks"` are not errors. An agent that stops with every field empty is
   status `"no_results"` (result still model-shaped, all defaults).

## Loop limit and errors

| Event | Handling | Status |
|---|---|---|
| `GraphRecursionError` | Same `_finalize` over the messages seen so far. No tool. N = count of ToolMessages. | `"partial"`, error `"recursion limit 12 hit after N searches"` |
| `_finalize` raises | Empty model-shaped result. | `"failed"` |
| Any other exception around the agent | Same as v1 `run_task` except branch. | `"failed"` |
| Tool raises inside | Caught in the tool, returned as text. Agent continues. | none |

`"partial"` is already in `DEGRADED_STATUSES`: checklist marks done, `synthesize_final_result` lists the agent
under `degraded`, webhook carries it.

## Settings and rollout

- `.env`: `INTELLIGENCE_VERSION=v2`, `RERANK_BACKEND=jev`, `TYPESAFE_API_KEY` set.
- Default stays v1 until a side-by-side run on one known tender shows v2 output at least as good for EMD and
  basic details. Flip default in a follow-up commit, delete v1 reasoning path later, not in this work.

## Testing

Unit, no network (same env placeholder trick as `tests/test_status_propagation.py`):

1. `tools.py`: stub `get_search_graph` returning two valid hits -> formatted text has both `[file, page]` headers
   and `sources` has two entries. Stub returning `[]` -> `"no relevant chunks"`. Stub raising -> `"search failed: ..."`.
2. `run_task.py`: fake chat model that answers with one tool call, then a final answer; stub tool. Assert envelope
   status `success`, result validates against `EMDAgentOutput`, sources length 1.
3. `run_task.py`: fake model that always emits a tool call -> `GraphRecursionError` path -> status `partial`,
   error mentions the limit, salvage called once.
4. `run_task.py`: agent `common_document_agent` -> v1 `run_task` called, v2 never builds an agent.
5. `graph.py`: `intelligence_version="v2"` picks the v2 node (assert node function identity).

Live: one tender through v1 and v2, compare `final_response.sections.emd_agent` and `basic_details` by eye.

## Out of scope

Document agents on ReAct, per-field evidence, a new orchestrator LLM, removing v1, changing the webhook payload,
making the recursion limit configurable.
