from typing import TypedDict


class KnowledgebaseState(TypedDict, total=False):
    # input
    mode: str          # "direct"
    collection: str    # qdrant collection to push into
    content: str       # exact text to embed

    # output
    vector_id: str
    status: str
    error: str | None
