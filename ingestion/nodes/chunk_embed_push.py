import logging
import re
import time
import uuid
from typing import Any

from ingestion.state import IngestionState
from core.config import settings
from core.retry import retry_on_429
from vector.qdrant import ensure_collection, qdrant

logger = logging.getLogger(__name__)

# ponytail: lazy singletons, load once per process. recreate when config changes and process restarts
_splitter = None
_dense_embedder = None
_sparse_embedder = None


def _get_splitter():
    global _splitter
    if _splitter is not None:
        return _splitter
    # ponytail: RecursiveCharacterTextSplitter default, no MarkdownHeader splitter until eval proves need
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        _splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )
    except ImportError:
        from langchain.text_splitter import RecursiveCharacterTextSplitter  # type: ignore

        _splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )
    return _splitter


def _get_dense_embedder():
    global _dense_embedder
    if _dense_embedder is not None:
        return _dense_embedder
    from langchain_openai import OpenAIEmbeddings

    api_key = (settings.openai_api_key or "").strip() if settings.openai_api_key else ""
    if not api_key:
        raise ValueError("OPENAI_API_KEY missing (set in .env)")
    _dense_embedder = OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=api_key,
        # ponytail: default retry, no custom backoff until rate-limit hit observed
    )
    return _dense_embedder


def _get_sparse_embedder():
    global _sparse_embedder
    if _sparse_embedder is not None:
        return _sparse_embedder
    # ponytail: BM25 local, no network, no SPLADE weights. upgrade to Splade_PP_en_v1 when neural sparse recall needed
    try:
        from fastembed import SparseTextEmbedding

        _sparse_embedder = SparseTextEmbedding(model_name="Qdrant/bm25")
    except Exception as e:
        logger.warning("sparse embedder init failed (BM25): %s, pushing dense only", e)
        _sparse_embedder = None
    return _sparse_embedder


@retry_on_429(max_retries=5, base=2.0, cap=60.0)
def _embed_documents_with_retry(embedder, batch_texts):
    return embedder.embed_documents(batch_texts)


# ponytail: table-aware chunking — keep | ... | blocks intact, header repeat when >chunk_size. O(n) scan
def _normalize_table_block(block: str) -> str:
    lines = []
    for l in block.split("\n"):
        if not l.strip():
            continue
        t = l.strip()
        # normalize pipes: "  |  a  |  b | " -> "| a | b |"
        t = re.sub(r"\s*\|\s*", " | ", t)
        t = re.sub(r" {2,}", " ", t).strip()
        if t and not t.startswith("|"):
            t = "| " + t
        if t and not t.endswith("|"):
            t = t + " |"
        # collapse duplicate pipes from fix
        t = re.sub(r"\|\s*\|", "| |", t)
        # trim again
        t = t.strip()
        lines.append(t)
    return "\n".join(lines)


def _split_markdown_by_tables(md: str) -> list[tuple[str, bool]]:
    # split into (block, is_table) preserving order. table = consecutive lines starting with |
    lines = md.split("\n")
    blocks: list[tuple[str, bool]] = []
    buf: list[str] = []
    tbl: list[str] = []
    for line in lines:
        is_tbl = line.strip().startswith("|")
        if is_tbl:
            if buf:
                blocks.append(("\n".join(buf), False))
                buf = []
            tbl.append(line)
        else:
            if tbl:
                blocks.append(("\n".join(tbl), True))
                tbl = []
            buf.append(line)
    if tbl:
        blocks.append(("\n".join(tbl), True))
    if buf:
        blocks.append(("\n".join(buf), False))
    return [(b, t) for b, t in blocks if b.strip()]


def _split_large_table(norm: str, chunk_size: int, overlap: int) -> list[str]:
    rows = [r for r in norm.split("\n") if r.strip()]
    if len(rows) <= 2:
        return [norm]
    header = rows[0]
    sep = rows[1] if "---" in rows[1] else None
    header_block = header + ("\n" + sep if sep else "")
    data = rows[2:] if sep else rows[1:]
    out: list[str] = []
    cur: list[str] = []
    cur_len = len(header_block) + 1
    for r in data:
        rl = len(r) + 1
        if cur and cur_len + rl > chunk_size:
            out.append(header_block + "\n" + "\n".join(cur))
            # ponytail: no overlap for tables, header repeat gives context cheaper than row overlap
            cur = []
            cur_len = len(header_block) + 1
        cur.append(r)
        cur_len += rl
    if cur:
        out.append(header_block + "\n" + "\n".join(cur))
    return out if out else [norm]


def chunk_embed_push(state: IngestionState) -> dict[str, Any]:
    parsed_pages: list[dict] = state.get("parsed_pages") or []
    document_id: str | None = state.get("document_id")
    job_id: str | None = state.get("job_id")
    reference_no: str | None = state.get("reference_no")
    document_tag: str | None = state.get("document_tag")

    # filter only parsed pages with markdown
    usable = [p for p in parsed_pages if p.get("status") == "parsed" and (p.get("markdown") or p.get("text"))]
    if not usable:
        err = "no parsed pages to chunk (parsed_pages empty or all failed)"
        logger.error("%s ref=%s tag=%s doc=%s", err, reference_no, document_tag, document_id)
        return {"status": "failed", "error": err, "chunks": [], "chunk_count": 0, "vector_ids": []}

    if not document_id:
        err = "document_id missing in state (run initialize_document first)"
        logger.error(err)
        return {"status": "failed", "error": err, "chunks": [], "chunk_count": 0, "vector_ids": []}

    # validate openai key early
    if not (settings.openai_api_key and settings.openai_api_key.strip()):
        err = "OPENAI_API_KEY missing, cannot embed"
        logger.error(err)
        return {"status": "failed", "error": err, "chunks": [], "chunk_count": 0, "vector_ids": []}

    splitter = _get_splitter()
    all_chunks: list[dict] = []

    for page in usable:
        page_no = page.get("page_no")
        markdown = page.get("markdown") or page.get("text") or ""
        if not markdown.strip():
            continue
        meta = page.get("metadata") or {}
        # table-aware split — ponytail: keep | tables intact, fallback to recursive splitter for prose
        texts: list[str] = []
        try:
            blocks = _split_markdown_by_tables(markdown)
            for block, is_table in blocks:
                if is_table:
                    norm = _normalize_table_block(block)
                    if len(norm) <= settings.chunk_size:
                        texts.append(norm)
                    else:
                        texts.extend(_split_large_table(norm, settings.chunk_size, settings.chunk_overlap))
                else:
                    # collapse padded spaces for prose but keep paragraph breaks
                    cleaned = re.sub(r" {2,}", " ", block)
                    if cleaned.strip():
                        texts.extend(splitter.split_text(cleaned))
            if not texts:
                texts = [markdown]
        except Exception as e:
            logger.warning("table-aware split failed page_no=%s: %s, fallback splitter", page_no, e)
            try:
                texts = splitter.split_text(markdown)
            except Exception:
                texts = [markdown]

        for idx, t in enumerate(texts):
            if not t.strip():
                continue
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}:{page_no}:{idx}"))
            payload_meta = {
                "document_id": document_id,
                "job_id": job_id,
                "reference_no": reference_no,
                "document_tag": document_tag,
                "document_name": meta.get("document_name") or state.get("document_name"),
                "original_url": meta.get("original_url") or state.get("original_url") or state.get("file_url"),
                "page_no": page_no,
                "total_pages": meta.get("total_pages") or state.get("total_pages"),
                "chunk_idx": idx,
                "chunk_count": len(texts),
            }
            all_chunks.append(
                {
                    "id": chunk_id,
                    "text": t,
                    "page_no": page_no,
                    "chunk_idx": idx,
                    "metadata": payload_meta,
                }
            )

    if not all_chunks:
        err = "chunking produced 0 chunks"
        logger.error("%s ref=%s", err, reference_no)
        return {"status": "failed", "error": err, "chunks": [], "chunk_count": 0, "vector_ids": []}

    logger.info("chunking done chunks=%s pages=%s ref=%s tag=%s doc=%s", len(all_chunks), len(usable), reference_no, document_tag, document_id)

    # ensure collection (hybrid dense+sparse) — ponytail: single collection, no per-doc sharding until >10M points
    try:
        coll = ensure_collection()
    except Exception as e:
        err = f"qdrant ensure_collection failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"status": "failed", "error": err, "chunks": all_chunks, "chunk_count": len(all_chunks), "vector_ids": []}

    # dense embed in batches — ponytail: decorator handles 429 exponential backoff, Retry-After, jitter
    texts = [c["text"] for c in all_chunks]
    dense_vectors: list[list[float]] = []
    try:
        embedder = _get_dense_embedder()
        batch = settings.embedding_batch_size or 100
        for i in range(0, len(texts), batch):
            batch_texts = texts[i : i + batch]
            vecs = _embed_documents_with_retry(embedder, batch_texts)
            dense_vectors.extend(vecs)
    except Exception as e:
        err = f"dense embedding failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"status": "failed", "error": err, "chunks": all_chunks, "chunk_count": len(all_chunks), "vector_ids": []}

    if len(dense_vectors) != len(all_chunks):
        err = f"dense vector count mismatch {len(dense_vectors)} != {len(all_chunks)}"
        logger.error(err)
        return {"status": "failed", "error": err, "chunks": all_chunks, "chunk_count": len(all_chunks), "vector_ids": []}

    # sparse embed (BM25) — optional, dense-only fallback
    sparse_vectors: list[Any] | None = None
    try:
        sparse_emb = _get_sparse_embedder()
        if sparse_emb is not None:
            # fastembed returns generator of SparseEmbedding
            raw = list(sparse_emb.embed(texts))
            # raw elements have .indices and .values (numpy arrays or lists)
            sparse_vectors = raw
            logger.info("sparse BM25 generated %s", len(raw))
    except Exception as e:
        logger.warning("sparse embedding failed, continuing dense only: %s", e)
        sparse_vectors = None

    # build points — ponytail: named vectors {"dense":..., "sparse": SparseVector} per PointStruct.extra=forbid
    from qdrant_client.http.models import PointStruct, SparseVector

    points: list[PointStruct] = []
    vector_ids: list[str] = []
    for idx, (c, dense) in enumerate(zip(all_chunks, dense_vectors)):
        sparse = None
        if sparse_vectors is not None:
            try:
                sv = sparse_vectors[idx]
                indices = sv.indices.tolist() if hasattr(sv.indices, "tolist") else list(sv.indices)
                values = sv.values.tolist() if hasattr(sv.values, "tolist") else list(sv.values)
                if indices and values:
                    sparse = SparseVector(indices=indices, values=values)
            except Exception as e:
                logger.warning("sparse vector build failed for chunk %s: %s", c["id"], e)
                sparse = None

        payload = {
            "text": c["text"],
            "page_no": c["page_no"],
            "pageNo": c["page_no"],
            "chunk_idx": c["metadata"]["chunk_idx"],
            "chunkIdx": c["metadata"]["chunk_idx"],
            "chunk_count": c["metadata"]["chunk_count"],
            "chunkCount": c["metadata"]["chunk_count"],
            "document_id": c["metadata"]["document_id"],
            "documentId": c["metadata"]["document_id"],
            "job_id": c["metadata"]["job_id"],
            "jobId": c["metadata"]["job_id"],
            "reference_no": c["metadata"]["reference_no"],
            "referenceNo": c["metadata"]["reference_no"],
            "document_tag": c["metadata"]["document_tag"],
            "documentTag": c["metadata"]["document_tag"],
            "document_type": c["metadata"]["document_tag"],
            "documentType": c["metadata"]["document_tag"],
            "document_name": c["metadata"]["document_name"],
            "documentName": c["metadata"]["document_name"],
            "original_url": c["metadata"]["original_url"],
            "originalUrl": c["metadata"]["original_url"],
            "total_pages": c["metadata"]["total_pages"],
            "totalPages": c["metadata"]["total_pages"],
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        # PointStruct.vector is Dict[str, Dense|SparseVector] for named vectors
        vector_dict: dict[str, Any] = {"dense": dense}
        if sparse is not None:
            vector_dict["sparse"] = sparse

        points.append(PointStruct(id=c["id"], vector=vector_dict, payload=payload))
        vector_ids.append(c["id"])

    # upsert in batches — ponytail: sync sequential batch, no parallel until profile says qdrant is bottleneck
    try:
        batch_size = 128
        for i in range(0, len(points), batch_size):
            batch_pts = points[i : i + batch_size]
            for attempt in range(3):
                try:
                    qdrant.upsert(collection_name=coll, points=batch_pts, wait=True)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    wait = 2**attempt
                    logger.warning("qdrant upsert batch %s failed attempt %s: %s retry %ss", i // batch_size, attempt + 1, e, wait)
                    time.sleep(wait)
        logger.info("qdrant push done collection=%s points=%s ref=%s tag=%s", coll, len(points), reference_no, document_tag)
    except Exception as e:
        err = f"qdrant upsert failed: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        return {"chunks": all_chunks, "chunk_count": len(all_chunks), "vector_ids": [], "status": "failed", "error": err}

    status = "indexed" if len(vector_ids) == len(all_chunks) else "partial"
    return {"chunks": all_chunks, "chunk_count": len(all_chunks), "vector_ids": vector_ids, "status": status, "error": None}
