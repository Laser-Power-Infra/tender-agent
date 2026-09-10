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
            _llm = ChatOpenAI(model=settings.chat_model, api_key=api_key, temperature=0)
    return _llm
