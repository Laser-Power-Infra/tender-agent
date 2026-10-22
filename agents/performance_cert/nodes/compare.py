"""Deterministic compare of performance-certificate PDFs for sameness.

No LLM here. Pages are matched per file by text fingerprint (difflib), values via
regex, and pipe-tables by normalized rows. Ambiguous findings go to ``unresolved``;
only real differences land in ``diffs``.
"""

import difflib
import logging
import re

logger = logging.getLogger(__name__)

MAX_FILES = 30          # contract: compare at most 30 unique PDFs
SIM_MIN = 0.6           # page text similarity below this is no evidence of sameness
PAIR_CONFIRM_MIN = 0.6  # candidate score we trust enough to report page-level diffs
FP_CHARS = 20000        # fingerprint cap keeps pairwise scoring cheap
MIN_TEXT = 20           # alnum chars before a page counts as machine-readable
MIN_DIFF_CHARS = 20     # a text change smaller than this is noise, not a finding

_NUM = re.compile(r"(?:rs\.?|inr|usd|eur|gbp|[$€£₹])\s*\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\b", re.I)
_DATE = re.compile(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{1,4}\b", re.I)
_ID = re.compile(r"\b[A-Z]{2,}[-/]?\d{2,}[A-Z0-9/-]*\b")
_TABLE_ROW = re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.M)
_WS = re.compile(r"\s+")
_ALNUM = re.compile(r"[A-Za-z0-9]")


def _ident(rec: dict) -> str:
    return (rec.get("sha256") or rec.get("file_url") or "").strip()


def _norm(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _alnum_len(text: str) -> int:
    return len(_ALNUM.findall(text or ""))


def _similar(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 4)


def _norm_row(row: str) -> str:
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    return "|".join(c for c in cells if c)


def _rows(text: str) -> list[str]:
    return [_norm_row(r) for r in _TABLE_ROW.findall(text or "")]


def _values(text: str) -> list[str]:
    """Value tokens (numbers, currency, dates, IDs); table rows excluded to avoid double counting."""
    body = "\n".join(line for line in (text or "").splitlines() if "|" not in line)
    toks = _NUM.findall(body) + _DATE.findall(body) + _ID.findall(body)
    return [t.replace(",", "").strip().lower() for t in toks]


def _multiset_delta(a_items: list[str], b_items: list[str]) -> tuple[list[str], list[str]]:
    ca: dict[str, int] = {}
    cb: dict[str, int] = {}
    for i in a_items:
        ca[i] = ca.get(i, 0) + 1
    for i in b_items:
        cb[i] = cb.get(i, 0) + 1
    only_a = sorted(t for t, n in ca.items() if n > cb.get(t, 0))
    only_b = sorted(t for t, n in cb.items() if n > ca.get(t, 0))
    return only_a, only_b


def _biggest_change(a: str, b: str) -> str:
    """Longest non-equal chunk of >= MIN_DIFF_CHARS alnum chars, or "" when none is meaningful."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    best = ""
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        chunk = (a[i1:i2] or b[j1:j2]).strip()
        if _alnum_len(chunk) >= MIN_DIFF_CHARS and len(chunk) > len(best):
            best = chunk
    return best


def _page_text(page: dict) -> str:
    return page.get("markdown") or ""


def _fingerprint(text: str) -> str:
    return _norm(text)[:FP_CHARS].lower()


def _pair_score(pages_a: list[dict], pages_b: list[dict], fp_a: str, fp_b: str) -> tuple[float, bool]:
    page_count_match = len(pages_a) == len(pages_b)
    sim = _similar(fp_a, fp_b)
    score = round(0.5 * (1.0 if page_count_match else 0.0) + 0.5 * sim, 4)
    return score, page_count_match


def _diff(a: str, b: str, page_no, kind: str, detail: str, va, vb) -> dict:
    return {"a_file": a, "b_file": b, "page_no": page_no, "kind": kind,
            "detail": _norm(detail)[:120], "a": va, "b": vb}


def _unresolved(a: str, b: str, page_no, reason: str, similarity: float) -> dict:
    return {"a_file": a, "b_file": b, "page_no": page_no, "reason": reason,
            "similarity": round(float(similarity), 4)}


def _page_diffs(a_id: str, b_id: str, no, pa: dict, pb: dict) -> tuple[list[dict], dict | None]:
    """Compare one aligned page pair. Returns (diffs, unresolved-or-None)."""
    if pa.get("status") == "failed" or pb.get("status") == "failed":
        return [], _unresolved(a_id, b_id, no, "low_confidence", 0.0)
    raw_a, raw_b = _page_text(pa), _page_text(pb)
    ta, tb = _norm(raw_a), _norm(raw_b)  # sim/chunks ignore layout whitespace; values/rows need raw lines
    sim = _similar(ta, tb)
    if min(_alnum_len(ta), _alnum_len(tb)) < MIN_TEXT:
        return [], _unresolved(a_id, b_id, no, "likely_visual", sim)
    if sim < SIM_MIN:
        return [], _unresolved(a_id, b_id, no, "low_similarity", sim)

    out: list[dict] = []
    only_a, only_b = _multiset_delta(_values(raw_a), _values(raw_b))
    for tok in only_a:
        out.append(_diff(a_id, b_id, no, "value", f"value only in a: {tok}", tok, ""))
    for tok in only_b:
        out.append(_diff(a_id, b_id, no, "value", f"value only in b: {tok}", "", tok))
    row_a, row_b = _multiset_delta(_rows(raw_a), _rows(raw_b))
    for row in row_a:
        out.append(_diff(a_id, b_id, no, "table", f"table row only in a: {row}", row, ""))
    for row in row_b:
        out.append(_diff(a_id, b_id, no, "table", f"table row only in b: {row}", "", row))
    if not out:
        change = _biggest_change(ta, tb)
        if change:
            out.append(_diff(a_id, b_id, no, "text", f"text differs: {change}", change, ""))
    return out, None


def _compare_pair(a_id: str, b_id: str, pages_a: list[dict], pages_b: list[dict],
                  score: float) -> tuple[list[dict], list[dict], list[dict]]:
    ma = {p.get("page_no"): p for p in pages_a}
    mb = {p.get("page_no"): p for p in pages_b}
    aligned, diffs, unresolved = [], [], []
    for no in sorted(set(ma) & set(mb), key=lambda n: (n is None, n)):
        aligned.append({"a_file": a_id, "b_file": b_id, "a_page": no, "b_page": no})
    if score < PAIR_CONFIRM_MIN:
        # pair itself is uncertain: one escalation for the pair, no page-level claims
        unresolved.append(_unresolved(a_id, b_id, None, "low_confidence", score))
        return aligned, diffs, unresolved
    for entry in aligned:
        no = entry["a_page"]
        page_diffs, page_unres = _page_diffs(a_id, b_id, no, ma[no], mb[no])
        diffs += page_diffs
        if page_unres:
            unresolved.append(page_unres)
    for no in sorted(set(ma) - set(mb), key=lambda n: (n is None, n)):
        diffs.append(_diff(a_id, b_id, no, "missing_page", f"page {no} only in a", str(no), ""))
    for no in sorted(set(mb) - set(ma), key=lambda n: (n is None, n)):
        diffs.append(_diff(a_id, b_id, no, "missing_page", f"page {no} only in b", "", str(no)))
    return aligned, diffs, unresolved


def compare(state: dict) -> dict:
    ref = (state.get("job_id") or "").strip()
    pages = state.get("pages") or []
    files = state.get("unique_files") or []

    ids = sorted({_ident(f) for f in files if _ident(f)})
    if not ids:
        ids = sorted({_ident(p) for p in pages if _ident(p)})
    ids = ids[:MAX_FILES]

    by_file: dict[str, list[dict]] = {i: [] for i in ids}
    for p in pages:
        i = _ident(p)
        if i in by_file:
            by_file[i].append(p)
    for i in by_file:
        by_file[i].sort(key=lambda p: p.get("page_no") or 0)
    fps = {i: _fingerprint(" ".join(_page_text(p) for p in by_file[i])) for i in ids}

    candidates: list[dict] = []
    aligned: list[dict] = []
    diffs: list[dict] = []
    unresolved: list[dict] = []

    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a_id, b_id = ids[x], ids[y]
            score, page_count_match = _pair_score(by_file[a_id], by_file[b_id], fps[a_id], fps[b_id])
            candidates.append({"a": a_id, "b": b_id, "score": score, "page_count_match": page_count_match})
            al, df, un = _compare_pair(a_id, b_id, by_file[a_id], by_file[b_id], score)
            aligned += al
            diffs += df
            unresolved += un

    if len(ids) < 2:
        logger.warning("compare ref=%s nothing to compare files=%s pages=%s", ref, len(ids), len(pages))
    logger.info("compare ref=%s files=%s candidates=%s aligned=%s diffs=%s unresolved=%s",
                ref, len(ids), len(candidates), len(aligned), len(diffs), len(unresolved))
    return {"candidates": candidates, "aligned": aligned, "diffs": diffs, "unresolved": unresolved}
