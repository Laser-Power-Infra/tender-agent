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


def _base_meta(state: dict, page_no: int, total: int) -> dict:
    return {
        "reference_no": state.get("reference_no"),
        "document_tag": state.get("document_tag"),
        "document_name": state.get("document_name") or (Path(state.get("file_path")).name if state.get("file_path") else None),
        "original_url": state.get("original_url") or state.get("file_url"),
        "document_id": state.get("document_id"),
        "job_id": state.get("job_id"),
        "page_no": page_no,
        "total_pages": total,
    }


def _resolve_paths(state: dict) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None, str | None]:
    return (
        state.get("file_path"),
        state.get("working_dir"),
        state.get("original_url") or state.get("file_url"),
        state.get("reference_no"),
        state.get("document_tag"),
        state.get("document_name"),
        state.get("document_id"),
    )


# ---------- pdf ----------

def parse_pdf(state: IngestionState) -> dict:
    """
    Docling parse for pdf. Preserves each page even if some fail.
    """
    file_path, working_dir, original_url, reference_no, document_tag, document_name, document_id = _resolve_paths(state)
    job_id = state.get("job_id")
    if not document_name and file_path:
        try:
            document_name = Path(file_path).name
        except Exception:
            pass
    if not file_path or not Path(file_path).exists():
        err = f"file_path missing: {file_path}"
        logger.error("%s ref=%s tag=%s", err, reference_no, document_tag)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}
    if not working_dir:
        working_dir = str(Path(file_path).parent)
    try:
        converter = _get_converter()
        logger.info("parse_pdf converting %s ref=%s tag=%s", file_path, reference_no, document_tag)
        result = converter.convert(source=file_path)
        doc = result.document

        pages = doc.pages if hasattr(doc, "pages") else []
        total = len(pages) if hasattr(pages, "__len__") else 0
        if total == 0:
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

        doc_cache = str(Path(working_dir) / "doc.json")
        try:
            d = doc.export_to_dict()
            Path(doc_cache).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("parse_pdf cache failed %s: %s", doc_cache, e)
            doc_cache = None

        parsed_pages: list[dict] = []
        ok = 0
        for i in range(1, total + 1):
            meta = _base_meta({**state, "document_name": document_name}, i, total)
            try:
                markdown = doc.export_to_markdown(page_no=i)
                text = markdown
                has_table = "|" in markdown if markdown else False
                status = "parsed" if markdown and markdown.strip() else "failed"
                err = None if status == "parsed" else "empty markdown"
                if status == "parsed":
                    ok += 1
                    logger.info("page parsed pdf page_no=%s/%s len=%s has_table=%s ref=%s", i, total, len(markdown), has_table, reference_no)
                    logger.info("page %s markdown:\n%s", i, markdown[:6000])
                else:
                    logger.error("page %s failed empty markdown ref=%s tag=%s", i, reference_no, document_tag)
                parsed_pages.append({"page_no": i, "markdown": markdown, "text": text, "metadata": meta, "status": status, "error": err})
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                logger.error("page %s failed ref=%s tag=%s error=%s", i, reference_no, document_tag, err, exc_info=True)
                parsed_pages.append({"page_no": i, "markdown": None, "text": None, "metadata": meta, "status": "failed", "error": err})

        status_final = "parsed" if ok == total and total > 0 else "partial" if ok > 0 else "failed"
        logger.info("parse_pdf done total=%s ok=%s fail=%s ref=%s tag=%s cache=%s", total, ok, total - ok, reference_no, document_tag, doc_cache)
        return {"total_pages": total, "parsed_pages": parsed_pages, "doc_cache": doc_cache, "status": status_final, "error": None if status_final != "failed" else "all pages failed"}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("parse_pdf failed ref=%s tag=%s error=%s", reference_no, document_tag, err, exc_info=True)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}


# backward compat alias
parse_document = parse_pdf


# ---------- docx ----------

def parse_docx(state: IngestionState) -> dict:
    """
    Docling parse for docx. No pypdf fallback (docx has no pdf pages).
    # ponytail: single logical page if docling pages empty; split if pagination later needed
    """
    file_path, working_dir, original_url, reference_no, document_tag, document_name, document_id = _resolve_paths(state)
    job_id = state.get("job_id")
    if not document_name and file_path:
        try:
            document_name = Path(file_path).name
        except Exception:
            pass
    if not file_path or not Path(file_path).exists():
        err = f"file_path missing: {file_path}"
        logger.error("%s ref=%s tag=%s", err, reference_no, document_tag)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}
    if not working_dir:
        working_dir = str(Path(file_path).parent)
    try:
        converter = _get_converter()
        logger.info("parse_docx converting %s ref=%s tag=%s", file_path, reference_no, document_tag)
        result = converter.convert(source=file_path)
        doc = result.document

        pages = doc.pages if hasattr(doc, "pages") else []
        total = len(pages) if hasattr(pages, "__len__") else 0
        if total == 0:
            try:
                d_tmp = doc.export_to_dict()
                total = len(d_tmp.get("pages", {}))
            except Exception:
                pass
            if total == 0:
                total = 1  # ponytail: docx no pdf pages, treat as single page

        doc_cache = str(Path(working_dir) / "doc.json")
        try:
            d = doc.export_to_dict()
            Path(doc_cache).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("parse_docx cache failed %s: %s", doc_cache, e)
            doc_cache = None

        parsed_pages: list[dict] = []
        ok = 0
        for i in range(1, total + 1):
            meta = _base_meta({**state, "document_name": document_name}, i, total)
            try:
                markdown = doc.export_to_markdown(page_no=i)
                text = markdown
                has_table = "|" in markdown if markdown else False
                status = "parsed" if markdown and markdown.strip() else "failed"
                err = None if status == "parsed" else "empty markdown"
                if status == "parsed":
                    ok += 1
                    logger.info("page parsed docx page_no=%s/%s len=%s has_table=%s ref=%s", i, total, len(markdown), has_table, reference_no)
                else:
                    logger.error("docx page %s failed empty markdown ref=%s", i, reference_no)
                parsed_pages.append({"page_no": i, "markdown": markdown, "text": text, "metadata": meta, "status": status, "error": err})
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                logger.error("docx page %s failed ref=%s error=%s", i, reference_no, err, exc_info=True)
                parsed_pages.append({"page_no": i, "markdown": None, "text": None, "metadata": meta, "status": "failed", "error": err})

        status_final = "parsed" if ok == total and total > 0 else "partial" if ok > 0 else "failed"
        logger.info("parse_docx done total=%s ok=%s ref=%s cache=%s", total, ok, reference_no, doc_cache)
        return {"total_pages": total, "parsed_pages": parsed_pages, "doc_cache": doc_cache, "status": status_final, "error": None if status_final != "failed" else "all pages failed"}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("parse_docx failed ref=%s tag=%s error=%s", reference_no, document_tag, err, exc_info=True)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}


# ---------- xlsx ----------

def _rows_to_markdown(rows: list[list]) -> str:
    # filter empty rows and stringify
    cleaned: list[list[str]] = []
    for r in rows:
        vals = [(str(v).strip() if v is not None else "") for v in r]
        # keep row if any non-empty
        if any(v for v in vals):
            # escape pipe and newline
            vals = [v.replace("|", "\\|").replace("\n", " ") for v in vals]
            cleaned.append(vals)
    if not cleaned:
        return ""
    # trim trailing empty cols
    max_cols = max(len(r) for r in cleaned)
    for r in cleaned:
        while len(r) < max_cols:
            r.append("")
    header = "| " + " | ".join(cleaned[0]) + " |"
    sep = "| " + " | ".join(["---"] * max_cols) + " |"
    body = ["| " + " | ".join(r) + " |" for r in cleaned[1:]]
    return "\n".join([header, sep] + body) if body else header + "\n" + sep


def parse_xlsx(state: IngestionState) -> dict:
    """
    Sheet-per-page parse for xlsx/xls/csv via openpyxl.
    Falls back to docling if openpyxl missing.
    # ponytail: sheet=page, O(n) scan; merged cells ignored until need
    """
    file_path, working_dir, original_url, reference_no, document_tag, document_name, document_id = _resolve_paths(state)
    if not document_name and file_path:
        try:
            document_name = Path(file_path).name
        except Exception:
            pass
    if not file_path or not Path(file_path).exists():
        err = f"file_path missing: {file_path}"
        logger.error("%s ref=%s tag=%s", err, reference_no, document_tag)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}
    if not working_dir:
        working_dir = str(Path(file_path).parent)

    # try openpyxl first
    try:
        from openpyxl import load_workbook

        logger.info("parse_xlsx openpyxl %s ref=%s tag=%s", file_path, reference_no, document_tag)
        wb = load_workbook(filename=str(file_path), read_only=True, data_only=True)
        sheets = wb.worksheets
        total = len(sheets) if sheets else 1
        parsed_pages: list[dict] = []
        ok = 0
        for idx, ws in enumerate(sheets, start=1):
            meta = _base_meta({**state, "document_name": document_name}, idx, total)
            # sheet name prefix for context
            try:
                rows = list(ws.iter_rows(values_only=True))
                markdown = _rows_to_markdown(rows)
                # prefix sheet name as heading if not empty
                if ws.title:
                    markdown = f"## {ws.title}\n\n" + markdown if markdown else f"## {ws.title}"
                text = markdown
                has_table = "|" in markdown
                status = "parsed" if markdown and markdown.strip() else "failed"
                err = None if status == "parsed" else "empty sheet"
                if status == "parsed":
                    ok += 1
                    logger.info("xlsx sheet parsed idx=%s/%s name=%s len=%s has_table=%s ref=%s", idx, total, ws.title, len(markdown), has_table, reference_no)
                else:
                    logger.warning("xlsx sheet %s empty ref=%s", idx, reference_no)
                parsed_pages.append({"page_no": idx, "markdown": markdown or None, "text": text or None, "metadata": meta, "status": status, "error": err})
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                logger.error("xlsx sheet %s failed ref=%s error=%s", idx, reference_no, err, exc_info=True)
                parsed_pages.append({"page_no": idx, "markdown": None, "text": None, "metadata": meta, "status": "failed", "error": err})
        try:
            wb.close()
        except Exception:
            pass
        # handle empty workbook
        if not parsed_pages:
            meta = _base_meta({**state, "document_name": document_name}, 1, 1)
            parsed_pages.append({"page_no": 1, "markdown": None, "text": None, "metadata": meta, "status": "failed", "error": "empty workbook"})
            total = 1
            ok = 0
        status_final = "parsed" if ok == total and total > 0 else "partial" if ok > 0 else "failed"
        return {"total_pages": total, "parsed_pages": parsed_pages, "doc_cache": None, "status": status_final, "error": None if status_final != "failed" else "all sheets failed"}
    except ImportError as e:
        logger.warning("openpyxl missing, fallback to docling for xlsx %s: %s", file_path, e)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("parse_xlsx openpyxl failed ref=%s error=%s, fallback to docling", reference_no, err, exc_info=True)

    # fallback: docling convert (handles xlsx via docling)
    try:
        converter = _get_converter()
        logger.info("parse_xlsx docling fallback %s ref=%s", file_path, reference_no)
        result = converter.convert(source=file_path)
        doc = result.document
        # treat as single page if no pagination
        try:
            markdown = doc.export_to_markdown()
        except Exception:
            markdown = ""
        total = 1
        meta = _base_meta({**state, "document_name": document_name}, 1, total)
        if markdown and markdown.strip():
            logger.info("xlsx docling fallback parsed len=%s ref=%s", len(markdown), reference_no)
            return {"total_pages": 1, "parsed_pages": [{"page_no": 1, "markdown": markdown, "text": markdown, "metadata": meta, "status": "parsed", "error": None}], "doc_cache": None, "status": "parsed", "error": None}
        else:
            return {"total_pages": 1, "parsed_pages": [{"page_no": 1, "markdown": None, "text": None, "metadata": meta, "status": "failed", "error": "empty markdown"}], "doc_cache": None, "status": "failed", "error": "empty markdown"}
    except Exception as e2:
        err = f"{type(e2).__name__}: {e2}"
        logger.error("parse_xlsx fallback failed ref=%s error=%s", reference_no, err, exc_info=True)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}


# ---------- txt ----------

def parse_txt(state: IngestionState) -> dict:
    """
    Stdlib read for txt. Single page.
    # ponytail: single page; split upstream if file > chunk_size
    """
    file_path, working_dir, original_url, reference_no, document_tag, document_name, document_id = _resolve_paths(state)
    if not document_name and file_path:
        try:
            document_name = Path(file_path).name
        except Exception:
            pass
    if not file_path or not Path(file_path).exists():
        err = f"file_path missing: {file_path}"
        logger.error("%s ref=%s tag=%s", err, reference_no, document_tag)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}

    try:
        p = Path(file_path)
        # ponytail: utf-8 first, fallback ignore; chardet only if garbled
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            # binary fallback
            text = p.read_bytes().decode("utf-8", errors="ignore")

        total = 1
        meta = _base_meta({**state, "document_name": document_name}, 1, total)
        markdown = text
        status = "parsed" if text and text.strip() else "failed"
        err = None if status == "parsed" else "empty text"
        if status == "parsed":
            logger.info("parse_txt parsed len=%s ref=%s tag=%s", len(text), reference_no, document_tag)
            logger.info("txt preview:\n%s", text[:4000])
        else:
            logger.warning("parse_txt empty file %s ref=%s", file_path, reference_no)
        return {"total_pages": total, "parsed_pages": [{"page_no": 1, "markdown": markdown or None, "text": text or None, "metadata": meta, "status": status, "error": err}], "doc_cache": None, "status": status, "error": err}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("parse_txt failed ref=%s error=%s", reference_no, err, exc_info=True)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}
