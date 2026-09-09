import logging
from sqlmodel import Session, select

from database.connection import engine
from database.models import Document, DocumentPage
from ingestion.state import IngestionState

logger = logging.getLogger(__name__)


def persist_document(state: IngestionState) -> dict:
    """
    Persist document + pages to DB. Idempotent on document_id.
    Runs parallel to chunk_embed_push after parse.
    # ponytail: sync Session per invoke, no async pool until throughput bottleneck proven
    # ponytail: delete+reinsert pages O(n), bulk upsert if >1k pages
    """
    document_id = state.get("document_id")
    if not document_id:
        logger.warning("persist skip: document_id missing")
        return {}

    job_id = state.get("job_id") or ""
    reference_no = state.get("reference_no") or ""
    document_tag = state.get("document_tag") or ""
    document_name = state.get("document_name")
    external_document_id = state.get("external_document_id")
    file_url = state.get("file_url") or state.get("original_url") or ""
    original_url = state.get("original_url") or file_url
    file_path = state.get("file_path")
    total_pages = state.get("total_pages")
    status = state.get("status") or "parsed"
    error = state.get("error")
    parsed_pages = state.get("parsed_pages") or []

    # chunk_count may not exist when parallel with chunk_embed_push
    chunk_count = state.get("chunk_count")

    try:
        with Session(engine) as session:
            # upsert Document by document_id
            existing = session.exec(select(Document).where(Document.document_id == document_id)).first()
            if existing:
                existing.job_id = job_id or existing.job_id
                existing.reference_no = reference_no or existing.reference_no
                existing.document_tag = document_tag
                existing.document_name = document_name
                existing.external_document_id = external_document_id
                existing.original_url = original_url or existing.original_url
                existing.file_url = file_url or existing.file_url
                existing.file_path = file_path
                existing.status = status
                existing.error = error
                existing.total_pages = total_pages
                if chunk_count is not None:
                    existing.chunk_count = chunk_count
                session.add(existing)
                session.commit()
                session.refresh(existing)
                logger.info("persist update document_id=%s external=%s pages=%s status=%s", document_id, external_document_id, total_pages, status)
            else:
                doc = Document(
                    document_id=document_id,
                    external_document_id=external_document_id,
                    job_id=job_id,
                    reference_no=reference_no,
                    document_tag=document_tag,
                    document_name=document_name,
                    original_url=original_url or "",
                    file_url=file_url or "",
                    file_path=file_path,
                    status=status,
                    error=error,
                    total_pages=total_pages,
                    chunk_count=chunk_count,
                )
                session.add(doc)
                session.commit()
                logger.info("persist insert document_id=%s external=%s pages=%s", document_id, external_document_id, total_pages)

            # pages: delete+reinsert for idempotency if parsed_pages present
            if parsed_pages:
                # remove old pages for this doc
                old = session.exec(select(DocumentPage).where(DocumentPage.document_id == document_id)).all()
                for o in old:
                    session.delete(o)
                session.commit()

                for p in parsed_pages:
                    page_no = p.get("page_no")
                    if not isinstance(page_no, int):
                        continue
                    md = p.get("markdown")
                    txt = p.get("text") or md
                    meta = p.get("metadata") or {}
                    session.add(
                        DocumentPage(
                            document_id=document_id,
                            external_document_id=external_document_id,
                            job_id=job_id,
                            reference_no=reference_no,
                            document_tag=document_tag,
                            page_no=page_no,
                            total_pages=p.get("metadata", {}).get("total_pages") or total_pages,
                            markdown=md,
                            text=txt,
                            status=p.get("status") or "parsed",
                            error=p.get("error"),
                            original_url=original_url,
                        )
                    )
                session.commit()
                logger.info("persist pages done document_id=%s count=%s", document_id, len(parsed_pages))

        return {}
    except Exception as e:
        logger.error("persist failed document_id=%s error=%s", document_id, e, exc_info=True)
        return {}
