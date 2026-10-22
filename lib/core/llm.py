import threading

from langchain_openai import ChatOpenAI

from lib.core.config import settings

# ponytail: one shared client per model, was one global for all models (first caller's model won).
# locked because the graph now fans tasks out across threads.
_llms = {}
_lock = threading.Lock()


def get_llm(chat_model: str = settings.chat_model):
    llm = _llms.get(chat_model)
    if llm is not None:
        return llm
    with _lock:
        if chat_model not in _llms:
            api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
            if not api_key:
                raise ValueError("OPENAI_API_KEY missing (set in .env)")
            # ponytail: temperature=0 used to be here and did nothing. langchain_openai pops it for
            # every gpt-5* non-chat model (chat_models/base.py validate_temperature), so the calls
            # ran at the default anyway. Pass reasoning_effort="none" if determinism is worth losing
            # reasoning for; leaving the dead argument in only implied a guarantee that was not there.
            _llms[chat_model] = ChatOpenAI(model=chat_model, api_key=api_key, timeout=120, max_retries=3)
    return _llms[chat_model]


if __name__ == "__main__":
    settings.openai_api_key = settings.openai_api_key or "sk-test"
    assert get_llm("a") is get_llm("a")
    assert get_llm("a") is not get_llm("b")
    assert get_llm("b").model_name == "b"
    print("llm ok")
