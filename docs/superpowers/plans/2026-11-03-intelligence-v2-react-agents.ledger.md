# SDD ledger — plan: docs/superpowers/plans/2026-11-03-intelligence-v2-react-agents.md
Branch: feat/intelligence-v2 (in place, no worktree — small plan, v1 default untouched)
Pre-flight: Task2 produces make_search_tool(reference_no, sources) -> consumed by Task3 build_agent: match. Task3 produces build_agent(agent, reference_no, sources, model=None), V2_AGENTS, _RECURSION_LIMIT -> consumed by Task4: match. Task1 produces v2 run_task stub -> Task4 replaces: match.
Task 1: Ruling: pytest not installed anywhere (venv, uv.lock) — tests written as house-style self-check scripts run with .venv/Scripts/python.exe tests/test_v2_agent.py, direct setattr instead of monkeypatch — cost if wrong: none, same assertions
Task 1: note: tests/test_document_agents.py and tests/test_final_merge.py fail on base commit 8ce0617 too, not caused by this plan
Task 1: complete (commits 8ce0617..beebf90, tests: env PYTHONPATH=. .venv/Scripts/python.exe tests/test_v2_agent.py → v2 agent self-check passed)
Task 2: complete (commits beebf90..dc51175, tests: env PYTHONPATH=. .venv/Scripts/python.exe tests/test_v2_agent.py → v2 agent self-check passed)
Task 3: Ruling: tool chunk header appends ', id <document_id>' when payload has one so the agent can fill evidence.documentId — v1 never exposed it either — cost if wrong: one extra token per chunk
Task 3: Ruling: GenericFakeChatModel.bind_tools raises NotImplementedError; tests subclass it returning self — test-only — cost if wrong: none
Task 3: complete (commits dc51175..712599f, tests: env PYTHONPATH=. .venv/Scripts/python.exe tests/test_v2_agent.py → v2 agent self-check passed)
Task 4: Ruling: create_react_agent does not raise GraphRecursionError at the limit, it emits AIMessage 'Sorry, need more steps to process this request.' (chat_agent_executor.py:689); run_task detects that sentinel, drops it, marks partial; GraphRecursionError catch kept as belt — cost if wrong: a langgraph upgrade changing the text turns partial into success silently
Task 4: Ruling: graph.py imports v2 run_task and settings lazily inside build_intelligence_graph — tests/test_fan_out.py stubs langgraph and imports the module — cost if wrong: none
Task 4: complete (commits 712599f..49d8885, tests: env PYTHONPATH=. .venv/Scripts/python.exe tests/test_v2_agent.py → v2 agent self-check passed)
Task 5: Ruling: live run showed chat completions returns 400 'Function tools with reasoning_effort are not supported for gpt-5.6-luna'; get_llm gained use_responses_api flag (cache keyed on it), v2 build_agent uses it, _finalize and v1 stay on chat completions — cost if wrong: responses api behaves differently on structured output or rate limits, v1 unaffected
Task 5: live 42261823 v2 all 4 agents success, no partial; v2 filled emdAmount, emdValidity, tender_fees that v1 left empty; v2 2x slower on reasoning agents (36s vs 26s emd, 37s vs 22s basic); basic_details made 14 searches via parallel tool calls
Task 5: complete (commits 49d8885..55a352a, tests: env PYTHONPATH=. .venv/Scripts/python.exe tests/test_v2_agent.py → v2 agent self-check passed)
Final review: reviewer subagent (fable), 0 critical, 3 important, 5 minor
Final: fixed finalize without system prompt — test_run_task_success_envelope (system msg assert) RED→GREEN, suite 13/13
Final: fixed responses api store=True default — test_responses_llm_does_not_store RED→GREEN; store=False + include reasoning.encrypted_content; live emd_agent on 42261823 success, 4 searches, 22.8s
Final: Ruling: parallel tool calls void the "12 ≈ 5 searches" bound — kept parallelism (more coverage per round, 37s for 14 searches), added prompt rule "at most 3 search_tender calls per turn" and sources dedupe (test_tool_dedupes_repeated_chunks RED→GREEN) — cost if wrong: up to 18 searches per agent burst JEV/Qdrant
Final: minor (deferred): tools._TOP_K=8 is dead, rerank caps valid at 5 (_MAX_VALID)
Final: minor (deferred): spec says all-fields-empty answer is status no_results, code says success
Final: minor (deferred): prompt has no rule for the agent's final message or for "search failed" replies
Final: minor (deferred): intelligence_version compared exactly, "V2" silently runs v1
