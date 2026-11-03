"""Self-check for intelligence v2 (agents/intelligence/v2): ReAct reasoning agents with a search tool.

Run: .venv/Scripts/python.exe tests/test_v2_agent.py
Needs no network: search subgraph and chat model are stubbed.
"""
import os

for _k, _v in {
    "DATABASE_URL": "postgresql://u:p@localhost:5432/d",
    "QDRANT_URL": "http://localhost:9001",
    "QDRANT_API_KEY": "x",
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672",
    "TEMP_DIR": "./tmp",
    "OPENAI_API_KEY": "sk-test",
}.items():
    os.environ.setdefault(_k, _v)


def test_graph_picks_v2_run_task():
    from lib.core.config import settings

    settings.intelligence_version = "v2"
    from agents.intelligence import graph as g
    from agents.intelligence.v2.run_task import run_task as v2

    compiled = g.build_intelligence_graph()
    assert compiled.builder.nodes["run_task"].runnable.func is v2
    settings.intelligence_version = "v1"
    from agents.intelligence.nodes.run_task import run_task as v1

    assert g.build_intelligence_graph().builder.nodes["run_task"].runnable.func is v1


if __name__ == "__main__":
    test_graph_picks_v2_run_task()
    print("v2 agent self-check passed")
