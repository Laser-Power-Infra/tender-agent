import logging

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PayloadSchemaType, SparseVectorParams, VectorParams

from core.config import settings

logger = logging.getLogger(__name__)

qdrant = QdrantClient(
    url=settings.qdrant_url,
    api_key=settings.qdrant_api_key,
)

# ponytail: single collection, single dense + one sparse. per-tenant split when >10M points
_MODEL_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

# ponytail: one list, was duplicated between the migrate branch and the create branch
_PAYLOAD_INDEXES = [
    ("reference_no", PayloadSchemaType.KEYWORD),
    ("referenceNo", PayloadSchemaType.KEYWORD),
    ("document_tag", PayloadSchemaType.KEYWORD),
    ("documentTag", PayloadSchemaType.KEYWORD),
    ("document_type", PayloadSchemaType.KEYWORD),
    ("documentType", PayloadSchemaType.KEYWORD),
    ("document_id", PayloadSchemaType.KEYWORD),
    ("documentId", PayloadSchemaType.KEYWORD),
    ("job_id", PayloadSchemaType.KEYWORD),
    ("jobId", PayloadSchemaType.KEYWORD),
    ("page_no", PayloadSchemaType.INTEGER),
    ("pageNo", PayloadSchemaType.INTEGER),
    ("chunk_idx", PayloadSchemaType.INTEGER),
    ("chunkIdx", PayloadSchemaType.INTEGER),
]

# ponytail: memo per (collection, dims). the check is 16 round-trips, it does not belong in the request path.
# a schema change needs a worker restart, which is already true for every other module singleton here.
_ensured: set[tuple[str, int]] = set()


def _dims_for(model: str) -> int:
    return _MODEL_DIMS.get(model, 1536)


def _create_payload_indexes(coll: str) -> None:
    for field, schema in _PAYLOAD_INDEXES:
        try:
            qdrant.create_payload_index(collection_name=coll, field_name=field, field_schema=schema)
        except Exception as e:
            # ponytail: index exists error ignored, log only real failures
            if "already exists" not in str(e).lower():
                logger.warning("payload index %s failed: %s", field, e)


def _needs_migrate(info, dims: int) -> bool:
    params = getattr(info.config, "params", None)
    vecs = getattr(params, "vectors", None) if params else None
    # old schema: vectors is VectorParams (unnamed) not dict with "dense"
    if vecs is not None and not isinstance(vecs, dict):
        return True
    if isinstance(vecs, dict) and "dense" not in vecs:
        return True
    if isinstance(vecs, dict) and "dense" in vecs:
        existing = getattr(vecs["dense"], "size", None)
        if existing and existing != dims:
            return True
    return False


def ensure_collection(name: str | None = None, embedding_model: str | None = None) -> str:
    coll = name or settings.qdrant_collection
    dims = _dims_for(embedding_model or settings.embedding_model)
    if (coll, dims) in _ensured:
        return coll

    if qdrant.collection_exists(collection_name=coll):
        # ponytail: destroy+recreate migration for unnamed->named change, no data migration (reindex).
        # a get_collection failure is a transport problem, not a schema verdict — raise, never delete.
        info = qdrant.get_collection(collection_name=coll)
        if _needs_migrate(info, dims):
            logger.warning("qdrant collection %s needs migrate (unnamed/dims mismatch) -> recreate dims=%s", coll, dims)
            qdrant.delete_collection(collection_name=coll)
        else:
            _create_payload_indexes(coll)
            _ensured.add((coll, dims))
            return coll

    logger.info("qdrant create_collection %s dims=%s", coll, dims)
    qdrant.create_collection(
        collection_name=coll,
        vectors_config={"dense": VectorParams(size=dims, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams()},
    )
    _create_payload_indexes(coll)
    _ensured.add((coll, dims))
    return coll
