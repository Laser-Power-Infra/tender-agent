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
        # ponytail: destroy+recreate migration for unnamed->named change, no data migration (reindex). check schema
        try:
            info = qdrant.get_collection(collection_name=coll)
            params = getattr(info.config, "params", None)
            vecs = getattr(params, "vectors", None) if params else None
            # old schema: vectors is VectorParams (unnamed) not dict with "dense"
            needs_migrate = False
            if vecs is not None and not isinstance(vecs, dict):
                needs_migrate = True
            elif isinstance(vecs, dict) and "dense" not in vecs:
                needs_migrate = True
            else:
                # also check dims mismatch
                if isinstance(vecs, dict) and "dense" in vecs:
                    existing = getattr(vecs["dense"], "size", None)
                    if existing and existing != dims:
                        needs_migrate = True
            if needs_migrate:
                logger.warning("qdrant collection %s needs migrate (unnamed/dims mismatch) -> recreate dims=%s", coll, dims)
                qdrant.delete_collection(collection_name=coll)
            else:
                # ensure alias indexes exist on existing collection (no recreate)
                for field, schema in [
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
                ]:
                    try:
                        qdrant.create_payload_index(collection_name=coll, field_name=field, field_schema=schema)
                    except Exception as e:
                        # ponytail: index exists error ignored, log only real failures
                        if "already exists" not in str(e).lower():
                            logger.warning("payload index %s failed: %s", field, e)
                return coll
        except Exception as e:
            logger.warning("qdrant get_collection check failed %s: %s, recreating", coll, e)
            try:
                qdrant.delete_collection(collection_name=coll)
            except Exception:
                pass
    logger.info("qdrant create_collection %s dims=%s", coll, dims)
    qdrant.create_collection(
        collection_name=coll,
        vectors_config={"dense": VectorParams(size=dims, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams()},
    )
    for field, schema in [
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
    ]:
        try:
            qdrant.create_payload_index(collection_name=coll, field_name=field, field_schema=schema)
        except Exception as e:
            logger.warning("payload index %s failed: %s", field, e)
    return coll