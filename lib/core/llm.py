import threading

from langchain_openai import ChatOpenAI

from lib.core.config import settings

# ponytail: one shared client per model, was one global for all models (first caller's model won).
# locked because the graph now fans tasks out across threads.
_llms = {}
_lock = threading.Lock()


def get_llm(chat_model: str = settings.chat_model, use_responses_api: bool = False):
    """use_responses_api: needed for function tools on gpt-5* with reasoning on; chat completions rejects them (400)."""
    key = (chat_model, use_responses_api)
    llm = _llms.get(key)
    if llm is not None:
        return llm
    with _lock:
        if key not in _llms:
            api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
            if not api_key:
                raise ValueError("OPENAI_API_KEY missing (set in .env)")
            # ponytail: temperature=0 used to be here and did nothing. langchain_openai pops it for
            # every gpt-5* non-chat model (chat_models/base.py validate_temperature), so the calls
            # ran at the default anyway. Pass reasoning_effort="none" if determinism is worth losing
            # reasoning for; leaving the dead argument in only implied a guarantee that was not there.
            # responses api defaults to store=True (30-day retention of every tender chunk on OpenAI's side);
            # chat completions never stored. store=False + encrypted reasoning keeps multi-turn reasoning working.
            extra = {"store": False, "include": ["reasoning.encrypted_content"]} if use_responses_api else {}
            _llms[key] = ChatOpenAI(model=chat_model, api_key=api_key, timeout=120, max_retries=3, use_responses_api=use_responses_api, **extra)
    return _llms[key]


if __name__ == "__main__":
    settings.openai_api_key = settings.openai_api_key or "sk-test"
    assert get_llm("a") is get_llm("a")
    assert get_llm("a") is not get_llm("b")
    assert get_llm("b").model_name == "b"
    assert get_llm("a", use_responses_api=True) is not get_llm("a")
    assert get_llm("a", use_responses_api=True).use_responses_api is True
    print("llm ok")
