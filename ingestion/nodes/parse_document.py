import logging
import os
from pathlib import Path

from ingestion.state import IngestionState

logger = logging.getLogger(__name__)

# ponytail: singleton converter, 1x 400s not Nx
_converter = None

# docling emits this between pages when asked, so one export yields every page
_PAGE_BREAK = "<!-- docling-page-break -->"

# ponytail: module constants, env override for tuning.
# Promote to core/config.py if a second module ever needs them.
_NUM_THREADS = int(os.getenv("DOCLING_NUM_THREADS", "4"))
_PAGE_BATCH = int(os.getenv("DOCLING_PAGE_BATCH", "5"))  # 0 disables batching


def _get_converter():
    global _converter
    if _converter is None:
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        # ponytail: cpu-only torch sizes its intra-op pool to the core count and docling
        # stacks its own on top -> 8 cores at 99% and the host stalls. Same fix as
        # rerank.py:32, different process. Must run before the first model load.
        import torch

        torch.set_num_threads(_NUM_THREADS)

        opts = PdfPipelineOptions()
        opts.accelerator_options = AcceleratorOptions(num_threads=_NUM_THREADS)
        _converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
        logger.info("docling converter ready threads=%s page_batch=%s", _NUM_THREADS, _PAGE_BATCH)
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


def _pdf_page_count(file_path: str) -> int | None:
    """Page count without running docling. None when the file is not a readable pdf."""
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(file_path)).pages) or None
    except Exception as e:
        logger.warning("pypdf page count failed for %s: %s", file_path, e)
        return None


def _page_count(doc, file_path: str, pdf_fallback: bool) -> int:
    pages = doc.pages if hasattr(doc, "pages") else []
    total = len(pages) if hasattr(pages, "__len__") else 0
    if total:
        return total
    try:
        total = len(doc.export_to_dict().get("pages", {}))
    except Exception:
        total = 0
    if total:
        return total
    if pdf_fallback:
        total = _pdf_page_count(file_path)
        if total:
            return total
    # ponytail: docx has no pdf pages, treat as single page
    return 1


def _page_markdowns(doc, total: int, start: int = 1) -> list[tuple[str | None, str | None]]:
    """Per-page (markdown, error) for `total` pages numbered from `start`.

    One export pass. export_to_markdown(page_no=i) walks the whole item list per call,
    so the per-page loop is O(pages x items) and stays as the fallback only.
    `start` is not 1 when the doc came from a page_range batch — its pages keep their
    original numbers, so the fallback must ask for those, not 1..total.
    """
    try:
        parts = doc.export_to_markdown(page_break_placeholder=_PAGE_BREAK).split(_PAGE_BREAK)
        if len(parts) == total:
            return [(p.strip() or None, None) for p in parts]
        logger.warning("page break split gave %s segments for %s pages, falling back to per-page export", len(parts), total)
    except Exception as e:
        logger.warning("single-pass markdown export failed (%s), falling back to per-page export", e)

    out: list[tuple[str | None, str | None]] = []
    for i in range(start, start + total):
        try:
            out.append((doc.export_to_markdown(page_no=i), None))
        except Exception as e:
            out.append((None, f"{type(e).__name__}: {e}"))
    return out


def _parse_with_docling(state: IngestionState, kind: str) -> dict:
    """Shared docling parse for pdf and docx. Page-level failures are preserved, not fatal."""
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
        converter = _get_converter()
        logger.info("%s converting %s ref=%s tag=%s", kind, file_path, reference_no, document_tag)
        # ponytail: one convert() holds every page's images at once, so a 10+ page pdf
        # spikes ram until the host dies. Convert in _PAGE_BATCH-page windows and drop
        # each doc before the next. Pdf only — docx/xlsx have no page model to slice.
        total = _pdf_page_count(file_path) if kind == "parse_pdf" else None

        if total and _PAGE_BATCH and total > _PAGE_BATCH:
            pages: list[tuple[str | None, str | None]] = []
            for start in range(1, total + 1, _PAGE_BATCH):
                end = min(start + _PAGE_BATCH - 1, total)
                logger.info("%s converting pages %s-%s/%s ref=%s", kind, start, end, total, reference_no)
                doc = converter.convert(source=file_path, page_range=(start, end)).document
                pages.extend(_page_markdowns(doc, end - start + 1, start=start))
                del doc  # drop this batch's page images before the next one, that is the point
        else:
            doc = converter.convert(source=file_path).document
            total = _page_count(doc, file_path, pdf_fallback=(kind == "parse_pdf"))
            pages = _page_markdowns(doc, total)

        parsed_pages: list[dict] = []
        ok = 0
        for i, (markdown, page_err) in enumerate(pages, start=1):
            meta = _base_meta({**state, "document_name": document_name}, i, total)
            if page_err:
                logger.error("%s page %s failed ref=%s tag=%s error=%s", kind, i, reference_no, document_tag, page_err)
                parsed_pages.append({"page_no": i, "markdown": None, "text": None, "metadata": meta, "status": "failed", "error": page_err})
            elif markdown and markdown.strip():
                ok += 1
                logger.info("page parsed %s page_no=%s/%s len=%s has_table=%s ref=%s", kind, i, total, len(markdown), "|" in markdown, reference_no)
                parsed_pages.append({"page_no": i, "markdown": markdown, "text": markdown, "metadata": meta, "status": "parsed", "error": None})
            else:
                logger.error("%s page %s failed empty markdown ref=%s tag=%s", kind, i, reference_no, document_tag)
                parsed_pages.append({"page_no": i, "markdown": None, "text": None, "metadata": meta, "status": "failed", "error": "empty markdown"})

        status_final = "parsed" if ok == total and total > 0 else "partial" if ok > 0 else "failed"
        logger.info("%s done total=%s ok=%s fail=%s ref=%s tag=%s", kind, total, ok, total - ok, reference_no, document_tag)
        return {"total_pages": total, "parsed_pages": parsed_pages, "status": status_final, "error": None if status_final != "failed" else "all pages failed"}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("%s failed ref=%s tag=%s error=%s", kind, reference_no, document_tag, err, exc_info=True)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}


# ---------- pdf ----------

def parse_pdf(state: IngestionState) -> dict:
    return _parse_with_docling(state, "parse_pdf")


# backward compat alias
parse_document = parse_pdf


# ---------- docx ----------

def parse_docx(state: IngestionState) -> dict:
    return _parse_with_docling(state, "parse_docx")


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
        return {"total_pages": total, "parsed_pages": parsed_pages, "status": status_final, "error": None if status_final != "failed" else "all sheets failed"}
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
            return {"total_pages": 1, "parsed_pages": [{"page_no": 1, "markdown": markdown, "text": markdown, "metadata": meta, "status": "parsed", "error": None}], "status": "parsed", "error": None}
        else:
            return {"total_pages": 1, "parsed_pages": [{"page_no": 1, "markdown": None, "text": None, "metadata": meta, "status": "failed", "error": "empty markdown"}], "status": "failed", "error": "empty markdown"}
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
        else:
            logger.warning("parse_txt empty file %s ref=%s", file_path, reference_no)
        return {"total_pages": total, "parsed_pages": [{"page_no": 1, "markdown": markdown or None, "text": text or None, "metadata": meta, "status": status, "error": err}], "status": status, "error": err}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("parse_txt failed ref=%s error=%s", reference_no, err, exc_info=True)
        return {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": err}
