import logging

from langchain_core.tools import tool

from agents.intelligence.state import is_done
from agents.intelligence.subagents.search.graph import get_search_graph
from agents.intelligence.subagents.specialized.nodes.execute_search import _provenance

logger = logging.getLogger(__name__)

_TOP_K = 8
_CHUNK_CHARS = 1200
_SOURCE_TEXT_CHARS = 500


def make_search_tool(reference_no: str, sources: list[dict]):
    """Search tool bound to one tender. Every hit the agent sees is also appended to `sources`, once per chunk."""
    seen: set = set()

    @tool
    def search_tender(query: str, keywords: list[str] = []) -> str:  # noqa: B006
        """Hybrid search inside this tender's documents. One question per call, 3 to 12 words.

        Args:
            query: one question in tender vocabulary, e.g. "EMD amount and payment mode".
            keywords: 2 to 5 exact terms, acronyms or form names, e.g. ["EMD", "earnest money", "bid security"].
        Returns:
            Relevant chunks as "[file, page N]" blocks, or "no relevant chunks", or "search failed: ...".
        """
        q = (query or "").strip()
        if not q:
            return "no relevant chunks"
        try:
            out = get_search_graph().invoke({"query": q, "keywords": list(keywords or []), "reference_no": reference_no})
        except Exception as e:
            logger.error("search_tender failed ref=%s query=%r: %s", reference_no, q[:80], e, exc_info=True)
            return f"search failed: {type(e).__name__}: {e}"
        if not is_done(out.get("status")):
            return f"search failed: {out.get('error') or out.get('status')}"
        hits = (out.get("valid") or [])[:_TOP_K]
        if not hits:
            logger.info("search_tender ref=%s query=%r keywords=%s -> no relevant chunks", reference_no, q[:80], len(keywords or []))
            return "no relevant chunks"
        blocks = []
        for h in hits:
            source_file, page = _provenance(h)
            text = h.get("text") or ""
            payload = h.get("payload") or {}
            doc_id = payload.get("document_id") or payload.get("documentId")
            header = f"[{source_file}, page {page if page is not None else 'unspecified'}" + (f", id {doc_id}]" if doc_id else "]")
            blocks.append(f"{header}\n{text[:_CHUNK_CHARS]}")
            if h.get("id") in seen:  # the agent still sees it; the webhook payload lists it once
                continue
            seen.add(h.get("id"))
            sources.append(
                {
                    "chunk_id": h.get("id"),
                    "document": "",
                    "text": text[:_SOURCE_TEXT_CHARS],
                    "score": h.get("rerank_score") if h.get("rerank_score") is not None else h.get("score"),
                    "source_file": source_file,
                    "page": page,
                }
            )
        logger.info("search_tender ref=%s query=%r keywords=%s -> %s chunks", reference_no, q[:80], len(keywords or []), len(hits))
        return "\n---\n".join(blocks)

    return search_tender
