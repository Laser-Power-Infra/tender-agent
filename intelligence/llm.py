import threading

from langchain_openai import ChatOpenAI

from core.config import settings

# ponytail: one shared client for every node, was six identical _llm globals.
# locked because the graph now fans tasks out across threads.
_llm = None
_lock = threading.Lock()


def get_llm():
    global _llm
    if _llm is not None:
        return _llm
    with _lock:
        if _llm is None:
            api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
            if not api_key:
                raise ValueError("OPENAI_API_KEY missing (set in .env)")
            # ponytail: temperature=0 used to be here and did nothing. langchain_openai pops it for
            # every gpt-5* non-chat model (chat_models/base.py validate_temperature), so the calls
            # ran at the default anyway. Pass reasoning_effort="none" if determinism is worth losing
            # reasoning for; leaving the dead argument in only implied a guarantee that was not there.
            _llm = ChatOpenAI(model=settings.chat_model, api_key=api_key, timeout=120, max_retries=3)
    return _llm
