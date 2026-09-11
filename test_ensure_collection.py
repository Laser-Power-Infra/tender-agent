"""Self-check for vector.qdrant.ensure_collection: memoization and the no-delete-on-error rule.

Run: python test_ensure_collection.py
Stubs qdrant_client and core.config so it needs no installed deps and no live server.
"""
import sys
import types


def _install_stubs():
    qc = types.ModuleType("qdrant_client")
    models = types.ModuleType("qdrant_client.http.models")
    http = types.ModuleType("qdrant_client.http")

    class _Enum:
        KEYWORD = "keyword"
        INTEGER = "integer"

    class _VectorParams:
        def __init__(self, size=None, distance=None):
            self.size = size
            self.distance = distance

    models.Distance = types.SimpleNamespace(COSINE="Cosine")
    models.PayloadSchemaType = _Enum
    models.VectorParams = _VectorParams
    models.SparseVectorParams = lambda *a, **k: object()
    http.models = models
    qc.http = http
    qc.QdrantClient = lambda **kw: _FakeClient()

    cfg = types.ModuleType("core.config")
    cfg.settings = types.SimpleNamespace(
        qdrant_url="http://stub",
        qdrant_api_key="stub",
        qdrant_collection="tender_chunks",
        embedding_model="text-embedding-3-small",
    )

    sys.modules.update({
        "qdrant_client": qc,
        "qdrant_client.http": http,
        "qdrant_client.http.models": models,
        "core.config": cfg,
    })
    return _VectorParams


class _FakeClient:
    """Counts calls so the test can assert the check runs once, not once per query."""

    def __init__(self):
        self.calls = {"collection_exists": 0, "get_collection": 0, "create_payload_index": 0, "delete_collection": 0}
        self.exists = True
        self.dense_size = 1536
        self.get_raises = False

    def collection_exists(self, collection_name):
        self.calls["collection_exists"] += 1
        return self.exists

    def get_collection(self, collection_name):
        self.calls["get_collection"] += 1
        if self.get_raises:
            raise ConnectionError("transient network blip")
        params = types.SimpleNamespace(vectors={"dense": _VP(self.dense_size)})
        return types.SimpleNamespace(config=types.SimpleNamespace(params=params))

    def create_payload_index(self, **kw):
        self.calls["create_payload_index"] += 1

    def delete_collection(self, collection_name):
        self.calls["delete_collection"] += 1

    def create_collection(self, **kw):
        pass


class _VP:
    def __init__(self, size):
        self.size = size


_install_stubs()
import vector.qdrant as q  # noqa: E402


def _fresh(**client_attrs):
    q._ensured.clear()
    client = _FakeClient()
    for k, v in client_attrs.items():
        setattr(client, k, v)
    q.qdrant = client
    return client


def test_memoized_after_first_call():
    client = _fresh()
    for _ in range(30):
        q.ensure_collection()
    assert client.calls["collection_exists"] == 1, client.calls
    assert client.calls["get_collection"] == 1, client.calls
    assert client.calls["create_payload_index"] == len(q._PAYLOAD_INDEXES), client.calls


def test_transient_error_never_deletes():
    client = _fresh(get_raises=True)
    try:
        q.ensure_collection()
    except ConnectionError:
        pass
    else:
        raise AssertionError("a transport failure must propagate, not be swallowed")
    assert client.calls["delete_collection"] == 0, "transient error must never drop the collection"
    assert not q._ensured, "a failed check must not be memoized"


def test_dim_mismatch_still_migrates():
    client = _fresh(dense_size=3072)
    q.ensure_collection()
    assert client.calls["delete_collection"] == 1, client.calls


if __name__ == "__main__":
    test_memoized_after_first_call()
    test_transient_error_never_deletes()
    test_dim_mismatch_still_migrates()
    print("ensure_collection self-check passed")
