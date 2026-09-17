import logging
import threading

from langchain_openai import OpenAIEmbeddings

from core.config import settings

try:
    from fastembed import SparseTextEmbedding
except ImportError:
    SparseTextEmbedding = None  # type: ignore

logger = logging.getLogger(__name__)

# ponytail: locked lazy singletons — shared by search and item subagents, searches run in parallel,
# an unlocked race loads BM25 twice
_dense_embedder = None
_sparse_embedder = None
_sparse_ready = False
_lock = threading.Lock()


def get_dense():
    global _dense_embedder
    if _dense_embedder is not None:
        return _dense_embedder
    with _lock:
        if _dense_embedder is None:
            api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
            if not api_key:
                raise ValueError("OPENAI_API_KEY missing")
            # ponytail: SDK retries 429 with backoff, no hand-rolled decorator
            _dense_embedder = OpenAIEmbeddings(model=settings.embedding_model, api_key=api_key, max_retries=5)
    return _dense_embedder


def get_sparse():
    global _sparse_embedder, _sparse_ready
    if _sparse_ready:
        return _sparse_embedder
    with _lock:
        if not _sparse_ready:
            if SparseTextEmbedding is None:
                logger.warning("fastembed not installed, dense-only fallback")
            else:
                try:
                    _sparse_embedder = SparseTextEmbedding(model_name="Qdrant/bm25")
                except Exception as e:
                    logger.warning("sparse BM25 init failed, dense-only fallback: %s", e)
                    _sparse_embedder = None
            _sparse_ready = True
    return _sparse_embedder