import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ponytail: singleton converter, load once per worker process to avoid N*400s
_converter = None


def _get_converter():
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter

        _converter = DocumentConverter()
    return _converter


def prepare_pages(state: dict) -> dict:
    """
    Single docling convert, cache dict to working_dir/doc.json.
    Fan-out reads cache, no N re-converts. Fixes len=0 and 3200s.
    """
    file_path = state.get("file_path")
    working_dir = state.get("working_dir")
    reference_no = state.get("reference_no")
    document_tag = state.get("document_tag")

    if not file_path or not Path(file_path).exists():
        err = f"file_path missing for prepare_pages: {file_path}"
        logger.error("%s ref=%s", err, reference_no)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}

    if not working_dir:
        working_dir = str(Path(file_path).parent)

    total = 0
    doc_cache = str(Path(working_dir) / "doc.json")

    try:
        converter = _get_converter()
        logger.info("prepare_pages converting %s ref=%s tag=%s", file_path, reference_no, document_tag)
        result = converter.convert(source=file_path)
        doc = result.document

        # accurate page break from docling
        pages = doc.pages if hasattr(doc, "pages") else []
        total = len(pages) if hasattr(pages, "__len__") else 0

        # cache full dict for per-page slicing (prov has page_no)
        try:
            d = doc.export_to_dict()
            Path(doc_cache).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            logger.info("prepare_pages cached doc.json total=%s ref=%s size=%s", total, reference_no, Path(doc_cache).stat().st_size)
        except Exception as e:
            logger.warning("prepare_pages cache failed %s: %s", doc_cache, e)
            doc_cache = None

        # fallback if doc.pages empty (scanned pdf)
        if total == 0:
            # try dict pages
            if doc_cache:
                try:
                    total = len(d.get("pages", {}))
                except Exception:
                    pass
            if total == 0:
                from pypdf import PdfReader

                reader = PdfReader(str(file_path))
                total = len(reader.pages)
                logger.info("prepare_pages pypdf fallback total=%s ref=%s", total, reference_no)

    except Exception as e:
        logger.warning("docling convert failed %s: %s, fallback to pypdf", file_path, e, exc_info=True)
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(file_path))
            total = len(reader.pages)
            logger.info("prepare_pages pypdf total=%s ref=%s", total, reference_no)
            doc_cache = None
        except Exception as e2:
            logger.warning("pypdf count failed %s: %s", file_path, e2)
            total = 1 if Path(file_path).exists() else 0
            doc_cache = None

    if total == 0:
        err = f"could not determine total_pages for {file_path}"
        logger.error("%s ref=%s", err, reference_no)
        return {"total_pages": 0, "parsed_pages": [], "doc_cache": doc_cache, "status": "failed", "error": err}

    logger.info("prepare_pages ready total=%s cache=%s ref=%s tag=%s", total, doc_cache, reference_no, document_tag)
    return {"total_pages": total, "parsed_pages": [], "doc_cache": doc_cache, "status": "prepared", "error": None}
