from qdrant_client import QdrantClient

from tender_agent.core.config import settings


qdrant = QdrantClient(
    url=settings.qdrant_url,
    api_key=settings.qdrant_api_key
)