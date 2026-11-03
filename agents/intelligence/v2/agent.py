import logging

from langgraph.prebuilt import create_react_agent

from agents.intelligence.v2.prompts import AGENT_PROMPTS
from agents.intelligence.v2.tools import make_search_tool
from lib.core.llm import get_llm

logger = logging.getLogger(__name__)

# each search round is 2 supersteps (llm + tool), so 12 is about 5 searches before the salvage path
_RECURSION_LIMIT = 12
V2_AGENTS = frozenset(AGENT_PROMPTS)


def build_agent(agent: str, reference_no: str, sources: list[dict], model=None):
    """ReAct agent for one reasoning section. Tool hits land in `sources`. `model` is for tests."""
    prompt = AGENT_PROMPTS[agent].format(reference_no=reference_no)
    graph = create_react_agent(model or get_llm(), [make_search_tool(reference_no, sources)], prompt=prompt)
    logger.info("built v2 agent=%s ref=%s", agent, reference_no)
    return graph.with_config(recursion_limit=_RECURSION_LIMIT)
