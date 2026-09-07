import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _extract_page_from_dict(doc_dict: dict, page_no: int) -> tuple[str, str]:
    """
    Prefer precomputed _page_markdowns (export_to_markdown page_no) which includes tables as pipes.
    Fallback to prov-based text join with table grid -> markdown table.
    """
    # fast path: cached per-page markdown with tables
    pms = doc_dict.get("_page_markdowns") or {}
    md = pms.get(str(page_no)) or pms.get(page_no)
    if md and md.strip():
        return md, md

    texts = doc_dict.get("texts", [])
    tables = doc_dict.get("tables", [])
    pictures = doc_dict.get("pictures", [])

    def _page_of(item: dict) -> int | None:
        prov = item.get("prov") or []
        if not prov:
            return None
        p = prov[0] if isinstance(prov, list) else prov
        return p.get("page_no") if isinstance(p, dict) else None

    def _table_to_md(table_item: dict) -> str:
        # build markdown table from grid
        data = table_item.get("data") or {}
        grid = data.get("grid") or []
        if not grid:
            return table_item.get("text") or ""
        # grid: list[row] -> list[cell] with text
        rows = []
        for row in grid:
            cells = []
            for cell in row:
                t = cell.get("text") or cell.get("content") or ""
                # escape pipe
                t = t.replace("|", "\\|").replace("\n", " ")
                cells.append(t.strip())
            rows.append(cells)
        if not rows:
            return ""
        # header row + separator
        header = "| " + " | ".join(rows[0]) + " |"
        sep = "| " + " | ".join(["---"] * len(rows[0])) + " |"
        body = ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join([header, sep] + body)

    def _text_of(item: dict) -> str:
        # table fallback
        if item in tables:
            md_tbl = _table_to_md(item)
            if md_tbl.strip():
                return md_tbl
        return item.get("text") or item.get("md") or item.get("content") or ""

    parts: list[str] = []
    for item in texts + tables + pictures:
        pg = _page_of(item)
        if pg == page_no:
            t = _text_of(item)
            if t:
                parts.append(t)

    markdown = "\n\n".join(parts)
    text = markdown
    return markdown, text


def parse_single_page(state: dict) -> dict:
    """
    LangGraph parallel node: handles exactly one page via cached doc.json.
    No re-convert. Preserves entry even on failure.
    """
    page_no = state.get("page_no")
    file_path = state.get("file_path")
    doc_cache = state.get("doc_cache")
    original_url = state.get("original_url") or state.get("file_url")
    reference_no = state.get("reference_no")
    document_tag = state.get("document_tag")
    document_name = state.get("document_name")
    document_id = state.get("document_id")
    job_id = state.get("job_id")
    total_pages = state.get("total_pages")

    if not document_name and file_path:
        try:
            document_name = Path(file_path).name
        except Exception:
            pass

    meta_base = {
        "reference_no": reference_no,
        "document_tag": document_tag,
        "document_name": document_name,
        "original_url": original_url,
        "document_id": document_id,
        "job_id": job_id,
        "page_no": page_no,
    }

    if not isinstance(page_no, int) or page_no < 1:
        err = f"invalid page_no: {page_no}"
        logger.error("page %s failed %s", page_no, err)
        return {"parsed_pages": [{"page_no": page_no, "markdown": None, "text": None, "metadata": meta_base, "status": "failed", "error": err}]}

    # try cache dict first (fast, no 400s)
    if doc_cache and Path(doc_cache).exists():
        try:
            doc_dict = json.loads(Path(doc_cache).read_text(encoding="utf-8"))
            markdown, text = _extract_page_from_dict(doc_dict, page_no)
            # total from dict if not passed
            if not total_pages:
                total_pages = len(doc_dict.get("pages", {})) or total_pages
            meta_base["total_pages"] = total_pages

            if markdown.strip():
                logger.info("page parsed page_no=%s/%s len=%s ref=%s tag=%s doc=%s source=cache", page_no, total_pages, len(markdown), reference_no, document_tag, document_name)
                logger.info("page %s markdown:\n%s", page_no, markdown[:4000])
                logger.info("page %s text:\n%s", page_no, text[:4000])
                return {"parsed_pages": [{"page_no": page_no, "markdown": markdown, "text": text, "metadata": meta_base, "status": "parsed", "error": None}]}
            else:
                logger.warning("page %s cache empty len=0 ref=%s tag=%s, fallback to docling single-page", page_no, reference_no, document_tag)
        except Exception as e:
            logger.warning("page %s cache read failed %s: %s, fallback to convert", page_no, doc_cache, e, exc_info=True)

    # fallback: single convert then dict slice (still better than page.export_to_markdown empty)
    try:
        from ingestion.nodes.prepare_pages import _get_converter

        converter = _get_converter()
        result = converter.convert(source=file_path)
        doc = result.document
        d = doc.export_to_dict()
        markdown, text = _extract_page_from_dict(d, page_no)
        if not total_pages:
            pages = d.get("pages", {})
            total_pages = len(pages) if isinstance(pages, dict) else len(pages) if hasattr(pages, "__len__") else 0
        meta_base["total_pages"] = total_pages

        if not markdown.strip():
            # last resort: doc.export_to_markdown page_no param (handles tables)
            try:
                full_md = doc.export_to_markdown(page_no=page_no)
                markdown = full_md if full_md else ""
                text = markdown
                logger.warning("page %s fallback page_md len=%s ref=%s has_table=%s", page_no, len(markdown), reference_no, "|" in markdown)
            except Exception:
                pass

        status = "parsed" if markdown.strip() else "failed"
        err = None if status == "parsed" else "empty markdown after all fallbacks"
        if status == "parsed":
            logger.info("page parsed page_no=%s/%s len=%s ref=%s tag=%s doc=%s source=convert", page_no, total_pages, len(markdown), reference_no, document_tag, document_name)
            logger.info("page %s markdown:\n%s", page_no, markdown[:4000])
            logger.info("page %s text:\n%s", page_no, text[:4000] if 'text' in locals() else markdown[:4000])
        else:
            logger.error("page %s failed empty markdown ref=%s tag=%s url=%s", page_no, reference_no, document_tag, original_url)

        return {"parsed_pages": [{"page_no": page_no, "markdown": markdown or None, "text": text or None, "metadata": meta_base, "status": status, "error": err}]}

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("page %s failed ref=%s tag=%s url=%s file=%s error=%s", page_no, reference_no, document_tag, original_url, file_path, err, exc_info=True)
        return {"parsed_pages": [{"page_no": page_no, "markdown": None, "text": None, "metadata": meta_base, "status": "failed", "error": err}]}
