from qdrant_client import QdrantClient

from core.config import settings


qdrant = QdrantClient(
    url=settings.qdrant_url,
    api_key=settings.qdrant_api_key
)