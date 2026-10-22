import threading

DEFAULT_MODEL = "jev-latest"

# ponytail: one shared JEV client per (api_key, model), same shape as lib/core/llm.py
_clients = {}
_lock = threading.Lock()


def get_jev(api_key: str | None, model: str | None = None):
    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("TYPESAFE_API_KEY missing (set in .env)")
    key = (api_key, model or DEFAULT_MODEL)
    client = _clients.get(key)
    if client is not None:
        return client
    with _lock:
        if key not in _clients:
            from typesafe_sdk import TypeSafeClient  # local: a missing dep fails this job, not the worker

            _clients[key] = TypeSafeClient(api_key=key[0], model=key[1])
    return _clients[key]


if __name__ == "__main__":
    import sys
    import types

    sys.modules["typesafe_sdk"] = types.SimpleNamespace(TypeSafeClient=lambda **kw: types.SimpleNamespace(**kw))
    assert get_jev("k") is get_jev(" k ", "jev-latest")
    assert get_jev("k", "other") is not get_jev("k")
    assert get_jev("k", "other").model == "other"
    try:
        get_jev("  ")
        raise AssertionError("empty key accepted")
    except ValueError:
        pass
    print("jev ok")
