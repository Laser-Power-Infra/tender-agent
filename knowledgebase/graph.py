import logging

from langgraph.graph import END, START, StateGraph

from core.config import settings
from knowledgebase.state import KnowledgebaseState

logger = logging.getLogger(__name__)


def embed_push(state: KnowledgebaseState) -> dict:
    """
    Embed one text and upsert a single qdrant point into `collection`.
    Dense + sparse vectors mirror ingestion.nodes.chunk_embed_push.
    # ponytail: single point, no chunking. content longer than chunk_size lands as one
    # oversized embedding — add chunking when long-content recall matters.
    """
    from uuid import NAMESPACE_DNS, uuid5

    from qdrant_client.http.models import PointStruct, SparseVector

    from ingestion.nodes.chunk_embed_push import _get_dense_embedder, _get_sparse_embedder
    from vector.qdrant import ensure_collection, qdrant

    content = (state.get("content") or "").strip()
    collection = state.get("collection") or settings.qdrant_collection

    if not content:
        logger.error("kb embed_push empty content collection=%s", collection)
        return {"status": "failed", "error": "content empty", "vector_id": ""}

    vector_id = str(uuid5(NAMESPACE_DNS, content))

    try:
        dense = _get_dense_embedder().embed_documents([content])[0]
    except Exception as e:
        err = f"dense embedding failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"status": "failed", "error": err, "vector_id": ""}

    vector_dict: dict = {"dense": dense}
    try:
        emb = _get_sparse_embedder()
        if emb is not None:
            sv = next(iter(emb.embed([content])))
            indices = sv.indices.tolist() if hasattr(sv.indices, "tolist") else list(sv.indices)
            values = sv.values.tolist() if hasattr(sv.values, "tolist") else list(sv.values)
            if indices and values:
                vector_dict["sparse"] = SparseVector(indices=indices, values=values)
    except Exception as e:
        logger.warning("kb sparse embedding failed, dense only: %s", e)

    try:
        ensure_collection(collection)
        point = PointStruct(id=vector_id, vector=vector_dict, payload={"text": content})
        qdrant.upsert(collection_name=collection, points=[point], wait=True)
    except Exception as e:
        err = f"qdrant upsert failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"status": "failed", "error": err, "vector_id": ""}

    logger.info("kb embed_push indexed collection=%s id=%s len=%s", collection, vector_id, len(content))
    return {"vector_id": vector_id, "status": "indexed", "error": None}


def build_knowledgebase_graph(checkpointer=None):
    logger.info("Building knowledgebase graph: START -> embed_push -> END checkpointer=%s", bool(checkpointer))
    graph = StateGraph(KnowledgebaseState)
    graph.add_node("embed_push", embed_push)
    graph.add_edge(START, "embed_push")
    graph.add_edge("embed_push", END)
    return graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
