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


def _dims_for(model: str) -> int:
    return _MODEL_DIMS.get(model, 1536)


def ensure_collection(name: str | None = None, embedding_model: str | None = None) -> str:
    coll = name or settings.qdrant_collection
    dims = _dims_for(embedding_model or settings.embedding_model)
    if qdrant.collection_exists(collection_name=coll):
        # ponytail: no dims check on exists, recreate only when model changes and migration needed
        return coll
    logger.info("qdrant create_collection %s dims=%s", coll, dims)
    qdrant.create_collection(
        collection_name=coll,
        vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
        sparse_vectors_config={"sparse": SparseVectorParams()},
    )
    for field, schema in [
        ("reference_no", PayloadSchemaType.KEYWORD),
        ("document_tag", PayloadSchemaType.KEYWORD),
        ("document_id", PayloadSchemaType.KEYWORD),
        ("page_no", PayloadSchemaType.INTEGER),
    ]:
        try:
            qdrant.create_payload_index(collection_name=coll, field_name=field, field_schema=schema)
        except Exception as e:
            logger.warning("payload index %s failed: %s", field, e)
    return coll