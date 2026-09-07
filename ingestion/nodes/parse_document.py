import json
import logging
from pathlib import Path

from ingestion.state import IngestionState

logger = logging.getLogger(__name__)

# ponytail: singleton converter, 1x 400s not Nx
_converter = None


def _get_converter():
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter

        _converter = DocumentConverter()
    return _converter


def parse_document(state: IngestionState) -> dict:
    """
    Single node owns page split via docling export_to_markdown(page_no=i).
    Preserves each page even if some fail. No fan-out.
    """
    file_path = state.get("file_path")
    working_dir = state.get("working_dir")
    original_url = state.get("original_url") or state.get("file_url")
    reference_no = state.get("reference_no")
    document_tag = state.get("document_tag")
    document_name = state.get("document_name") or (Path(file_path).name if file_path else None)
    document_id = state.get("document_id")
    job_id = state.get("job_id")

    if not file_path or not Path(file_path).exists():
        err = f"file_path missing: {file_path}"
        logger.error("%s ref=%s tag=%s", err, reference_no, document_tag)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}

    if not working_dir:
        working_dir = str(Path(file_path).parent)

    try:
        converter = _get_converter()
        logger.info("parse_document converting %s ref=%s tag=%s", file_path, reference_no, document_tag)
        result = converter.convert(source=file_path)
        doc = result.document

        pages = doc.pages if hasattr(doc, "pages") else []
        total = len(pages) if hasattr(pages, "__len__") else 0
        if total == 0:
            # fallback count via dict or pypdf
            try:
                d_tmp = doc.export_to_dict()
                total = len(d_tmp.get("pages", {}))
            except Exception:
                pass
            if total == 0:
                try:
                    from pypdf import PdfReader

                    total = len(PdfReader(str(file_path)).pages)
                except Exception:
                    total = 1

        # cache dict + page map for debug
        doc_cache = str(Path(working_dir) / "doc.json")
        try:
            d = doc.export_to_dict()
            # store for later inspection
            Path(doc_cache).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("parse_document cache failed %s: %s", doc_cache, e)
            doc_cache = None

        parsed_pages: list[dict] = []
        ok = 0

        for i in range(1, total + 1):
            meta = {
                "reference_no": reference_no,
                "document_tag": document_tag,
                "document_name": document_name,
                "original_url": original_url,
                "document_id": document_id,
                "job_id": job_id,
                "page_no": i,
                "total_pages": total,
            }
            try:
                markdown = doc.export_to_markdown(page_no=i)
                text = markdown
                # markdown includes tables as | pipes when present
                has_table = "|" in markdown
                status = "parsed" if markdown and markdown.strip() else "failed"
                err = None if status == "parsed" else "empty markdown"
                if status == "parsed":
                    ok += 1
                    logger.info("page parsed page_no=%s/%s len=%s has_table=%s ref=%s tag=%s", i, total, len(markdown), has_table, reference_no, document_tag)
                    logger.info("page %s markdown:\n%s", i, markdown[:6000])
                    logger.info("page %s text len=%s", i, len(text or ""))
                else:
                    logger.error("page %s failed empty markdown ref=%s tag=%s", i, reference_no, document_tag)
                parsed_pages.append({"page_no": i, "markdown": markdown, "text": text, "metadata": meta, "status": status, "error": err})
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                logger.error("page %s failed ref=%s tag=%s url=%s error=%s", i, reference_no, document_tag, original_url, err, exc_info=True)
                parsed_pages.append({"page_no": i, "markdown": None, "text": None, "metadata": meta, "status": "failed", "error": err})

        status_final = "parsed" if ok == total and total > 0 else "partial" if ok > 0 else "failed"
        logger.info("parse_document done total=%s ok=%s fail=%s ref=%s tag=%s cache=%s", total, ok, total - ok, reference_no, document_tag, doc_cache)
        return {"total_pages": total, "parsed_pages": parsed_pages, "doc_cache": doc_cache, "status": status_final, "error": None if status_final != "failed" else "all pages failed"}

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("parse_document failed ref=%s tag=%s url=%s error=%s", reference_no, document_tag, original_url, err, exc_info=True)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}
