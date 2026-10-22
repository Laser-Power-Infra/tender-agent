"""LLM extraction of dates, party reference, issuer and items from each unique PDF.

The raw pdf bytes go to the model as-is (not the docling markdown): the certificate layout
carries the dates and the reference number, and re-rendering it as text can lose them.
One file, one call; any per-file failure degrades to nulls so the job never dies here.
"""

import base64
import logging
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from lib.core.llm import get_llm

logger = logging.getLogger(__name__)

PROMPT = (
    "Read the attached performance-certificate PDF and return exactly these fields:\n"
    "- issuing_date: the date the certificate was issued\n"
    "- signing_date: the date it was signed\n"
    "- party_reference_no: the party/vendor reference number (e.g. LC/WBSEDCL/... or a PO/reference no)\n"
    "- party_name: the organisation that issued the certificate (letterhead or signatory's organisation)\n"
    "- utility_or_client: UTILITY if that organisation is a government department, state electricity board, "
    "discom/transco/genco, PSU, railways, municipal or other public body; CLIENT if it is a private company or contractor\n"
    "- items: each supplied item description exactly as written in the certificate\n"
    "Return null for any field that is not present in the document. Never guess or infer a value."
)


class CertDetails(BaseModel):
    issuing_date: str | None = None
    signing_date: str | None = None
    party_reference_no: str | None = None
    party_name: str | None = None
    utility_or_client: Literal["UTILITY", "CLIENT"] | None = None
    items: list[str] = []


def _empty(uf: dict) -> dict:
    return {
        "certificate_id": uf.get("certificate_id"),
        "sha256": uf.get("sha256"),
        "issuing_date": None,
        "signing_date": None,
        "party_reference_no": None,
        "party_name": None,
        "utility_or_client": None,
        "items": [],
    }


def details(state: dict) -> dict:
    """LangGraph node: one LLM call per unique pdf, extracting its certificate fields."""
    ref = (state.get("job_id") or "").strip() or None
    unique_files = state.get("unique_files") or []
    out: list[dict] = []

    for uf in unique_files:
        entry = _empty(uf)
        try:
            b64 = base64.b64encode(Path(uf["file_path"]).read_bytes()).decode()
            msg = HumanMessage(
                content=[
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "file",
                        "base64": b64,
                        "mime_type": "application/pdf",
                        "filename": uf.get("file_name") or Path(uf["file_path"]).name,
                    },
                ]
            )
            res = get_llm().with_structured_output(CertDetails).invoke([msg])
            if res:
                entry["issuing_date"] = res.issuing_date
                entry["signing_date"] = res.signing_date
                entry["party_reference_no"] = res.party_reference_no
                entry["party_name"] = res.party_name
                entry["utility_or_client"] = res.utility_or_client
                entry["items"] = res.items
        except Exception as e:
            logger.error("details ref=%s file=%s error=%s", ref, uf.get("file_path"), f"{type(e).__name__}: {e}", exc_info=True)
        out.append(entry)

    logger.info("details ref=%s files=%d", ref, len(out))
    return {"details": out}


if __name__ == "__main__":
    import tempfile

    class FakeLLM:
        def __init__(self, res=None, boom=False):
            self._res = res
            self._boom = boom

        def with_structured_output(self, _):
            def invoke(_msgs):
                if self._boom:
                    raise RuntimeError("boom")
                return self._res
            return type("S", (), {"invoke": staticmethod(invoke)})()

    root = Path(tempfile.mkdtemp())
    paths = []
    for name in ("a.pdf", "b.pdf"):
        p = root / name
        p.write_bytes(b"%PDF-1.4 " + name.encode())
        paths.append(str(p))

    unique_files = [
        {"certificate_id": "C1", "sha256": "h1", "file_name": "a.pdf", "file_path": paths[0]},
        {"certificate_id": "C2", "sha256": "h2", "file_name": "b.pdf", "file_path": paths[1]},
    ]

    got = CertDetails(
        issuing_date="2024-01-01",
        signing_date="2024-01-02",
        party_reference_no="LC/WBSEDCL/1",
        party_name="WBSEDCL",
        utility_or_client="UTILITY",
        items=["3C x 300 SQMM XLPE 11KV"],
    )
    details.__globals__["get_llm"] = lambda: FakeLLM(res=got)
    r = details({"job_id": "R1", "unique_files": unique_files})
    assert len(r["details"]) == 2, r
    assert r["details"][0] == {
        "certificate_id": "C1",
        "sha256": "h1",
        "issuing_date": "2024-01-01",
        "signing_date": "2024-01-02",
        "party_reference_no": "LC/WBSEDCL/1",
        "party_name": "WBSEDCL",
        "utility_or_client": "UTILITY",
        "items": ["3C x 300 SQMM XLPE 11KV"],
    }, r
    assert r["details"][1]["certificate_id"] == "C2", r

    # a raising model -> nulls, still one entry per file, no crash
    details.__globals__["get_llm"] = lambda: FakeLLM(boom=True)
    r = details({"job_id": "R2", "unique_files": unique_files})
    assert len(r["details"]) == 2 and r["details"][0]["issuing_date"] is None, r
    assert r["details"][0]["certificate_id"] == "C1" and r["details"][0]["sha256"] == "h1", r

    # empty input -> empty list
    r = details({"job_id": "R3", "unique_files": []})
    assert r == {"details": []}, r
    print("details ok")
