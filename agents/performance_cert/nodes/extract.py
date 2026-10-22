import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from lib.core.config import settings
from lib.documents.download import download_document
from lib.documents.parse import parse_pdf
from agents.performance_cert.state import PerformanceCertState

logger = logging.getLogger(__name__)


def _sha256(path: str) -> str:
    """Streamed hash, so a big pdf never lands in memory whole."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_all(state: PerformanceCertState, files: list[dict], root: Path):
    """Download every file, hash it, keep the first per hash. Returns (unique_files, duplicates, errors).

    Each file gets its own subdir so same-named files cannot overwrite each other before hashing.
    """
    ref = state.get("job_id")
    seen: dict[str, dict] = {}
    groups: dict[str, list[str]] = {}
    errors: list[str] = []

    for idx, f in enumerate(files):
        url = (f.get("file_url") or "").strip()
        if not url:
            errors.append("missing file_url")
            logger.warning("extract ref=%s idx=%s missing file_url", ref, idx)
            continue

        sub = root / f"{idx:02d}-{uuid4()}"
        res = download_document({"file_url": url, "working_dir": str(sub)})
        path = res.get("file_path")
        if res.get("status") != "downloaded" or not path:
            err = res.get("error") or "download failed"
            errors.append(f"{url}: {err}")
            logger.error("extract ref=%s download failed url=%s error=%s", ref, url, err)
            continue

        sha = _sha256(path)
        cid = f.get("certificate_id")
        cid = str(cid).strip() if cid is not None else ""
        # every entry needs an id, so fall back to the name, then the url
        groups.setdefault(sha, []).append(cid or (f.get("file_name") or "").strip() or url)
        if sha not in seen:
            seen[sha] = {
                "certificate_id": cid,
                "file_url": url,
                "file_name": f.get("file_name"),
                "file_tag": f.get("file_tag"),
                "sha256": sha,
                "file_path": path,
            }

    # one-way: the first file of a byte-identical group is canonical, the rest point at it.
    # a single-file payload has nothing to duplicate, so skip the check entirely.
    duplicates = [] if len(files) < 2 else [
        {"certificate_id": cid, "sha256": sha, "duplicate_of": [] if cid == ids[0] else [ids[0]]}
        for sha, ids in groups.items()
        for cid in ids
    ]
    return list(seen.values()), duplicates, errors


def _parse_unique(state: PerformanceCertState, unique_files: list[dict]):
    """Parse one representative per unique hash (byte-identical files need no re-parse).

    Returns (pages, any_failed). Page-level failures are preserved, not fatal.
    No page images rendered here - kept lazy for the vision escalation step.
    """
    ref = state.get("job_id")
    pages: list[dict] = []
    any_failed = False

    for uf in unique_files:
        res = parse_pdf(
            {
                "file_path": uf["file_path"],
                "working_dir": str(Path(uf["file_path"]).parent),
                "job_id": ref,
                "document_tag": uf.get("file_tag"),
                "document_name": uf.get("file_name"),
                "original_url": uf.get("file_url"),
            }
        )
        total = res.get("total_pages") or 0
        if res.get("status") == "failed":
            any_failed = True
            logger.error("extract ref=%s parse failed url=%s error=%s", ref, uf.get("file_url"), res.get("error"))

        for p in res.get("parsed_pages") or []:
            if p.get("status") != "parsed":
                any_failed = True
            pages.append(
                {
                    "file_url": uf.get("file_url"),
                    "sha256": uf["sha256"],
                    "page_no": p.get("page_no"),
                    "total_pages": total,
                    "markdown": p.get("markdown"),
                    "status": p.get("status"),
                    "error": p.get("error"),
                }
            )

    return pages, any_failed


def extract(state: PerformanceCertState) -> dict:
    """LangGraph node: download, hash-dedup, then parse one representative per unique pdf.

    Byte-identical files are collapsed before parsing, so 30 submissions cost one parse per
    distinct document. Page failures are preserved in `pages`, never fatal.
    """
    ref = (state.get("job_id") or "").strip() or None
    files = state.get("files") or []
    if not files:
        logger.error("extract ref=%s no files", ref)
        return {"unique_files": [], "duplicates": [], "pages": [], "status": "failed", "error": "no files"}

    max_pdfs = int(getattr(settings, "performance_cert_max_pdfs", 30) or 30)
    if len(files) > max_pdfs:
        logger.warning("extract ref=%s files=%d exceeds performance_cert_max_pdfs=%d, capping", ref, len(files), max_pdfs)
        files = files[:max_pdfs]

    root = Path(settings.temp_dir) / (ref or str(uuid4()))
    root.mkdir(parents=True, exist_ok=True)

    unique_files, duplicates, errors = _download_all(state, files, root)
    pages, parse_failed = _parse_unique(state, unique_files)

    if not pages:
        status = "failed"
        error = "; ".join(errors) if errors else "no pages extracted"
    elif parse_failed or errors:
        status = "partial"
        error = None
    else:
        status = "extracted"
        error = None

    logger.info(
        "extract ref=%s files=%d unique=%d duplicate_entries=%d pages=%d status=%s",
        ref, len(files), len(unique_files), len(duplicates), len(pages), status,
    )
    return {
        "unique_files": unique_files,
        "duplicates": duplicates,
        "pages": pages,
        "status": status,
        "error": error,
    }


if __name__ == "__main__":
    contents = {"u1": b"same-bytes", "u2": b"same-bytes", "u3": b"other-bytes"}

    def fake_download(st):
        key = st["file_url"].rsplit("/", 1)[-1]
        d = Path(st["working_dir"])
        d.mkdir(parents=True, exist_ok=True)
        p = d / key
        p.write_bytes(contents[key])
        return {"file_path": str(p), "status": "downloaded", "error": None}

    def fake_parse(st):
        return {"total_pages": 1, "parsed_pages": [{"page_no": 1, "markdown": "x", "text": "x", "status": "parsed", "error": None}], "status": "parsed", "error": None}

    extract.__globals__["download_document"] = fake_download
    extract.__globals__["parse_pdf"] = fake_parse

    st = {
        "job_id": "R1",
        "files": [
            {"file_url": "http://x/u1", "file_name": "u1.pdf", "file_tag": "a", "certificate_id": "C1"},
            {"file_url": "http://x/u2", "file_name": "u2.pdf", "file_tag": "b", "certificate_id": "C2"},
            {"file_url": "http://x/u3", "file_name": "u3.pdf", "file_tag": "c"},  # no id -> falls back to file_name
        ],
    }
    r = extract(st)
    assert r["status"] == "extracted", r
    assert len(r["unique_files"]) == 2, r  # u1/u2 collapse
    dupes = {d["certificate_id"]: d for d in r["duplicates"]}
    assert len(r["duplicates"]) == 3 and set(dupes) == {"C1", "C2", "u3.pdf"}, r  # one entry per downloaded file
    assert dupes["C1"]["duplicate_of"] == [], r  # first of the identical pair is canonical
    assert dupes["C2"]["duplicate_of"] == ["C1"], r  # the other points back at it, one way
    assert dupes["u3.pdf"]["duplicate_of"] == [], r  # unique -> empty
    assert dupes["C1"]["sha256"] == hashlib.sha256(b"same-bytes").hexdigest(), r
    assert len(r["pages"]) == 2, r  # one page per unique file, not per input
    assert r["pages"][0]["sha256"] and r["pages"][0]["page_no"] == 1, r

    # single file -> duplicate check skipped
    r = extract({"job_id": "R3", "files": [{"file_url": "http://x/u1", "file_name": "u1.pdf", "file_tag": "a", "certificate_id": "C1"}]})
    assert r["duplicates"] == [] and len(r["pages"]) == 1, r

    # a parse that fails everywhere -> failed, not a crash
    extract.__globals__["parse_pdf"] = lambda st: {"total_pages": 0, "parsed_pages": [], "status": "failed", "error": "boom"}
    r = extract(st)
    assert r["status"] == "failed" and r["error"], r

    # empty input -> failed
    r = extract({"job_id": "R2", "files": []})
    assert r["status"] == "failed" and not r["pages"], r
    print("extract ok")
