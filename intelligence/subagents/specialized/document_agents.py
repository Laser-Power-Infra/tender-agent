"""One agent per inner section of TENDER_DOCUMENTS, generated at import time.

Every section asks the same question — which of these documents does this tender require? — which is
what company_document_finder already answers for its own hand-written list. So this is not 52 agent
designs; it is one agent shape registered 52 times from data.

Agent name is "{bucket}.{section}", e.g. "common.gst". The dot keeps these keys disjoint from the
hand-written agent names, which contain none.
"""
import logging
import re

from constants.tender_documents import TENDER_DOCUMENTS
from intelligence.subagents.specialized.company_documents import COMPANY_DOCUMENT_QUERIES

logger = logging.getLogger(__name__)


def _norm(document: str) -> str:
    """Lookup key for KEYWORD_OVERRIDES: case, punctuation and licence/license insensitive."""
    s = document.lower().replace("licence", "license").replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _twin(document: str) -> str | None:
    """The other spelling of licence/license.

    TENDER_DOCUMENTS uses "Licence" throughout; real tenders use both. BM25 tokenizes them as two
    different terms, so the variant is a genuinely new token rather than a restatement.
    """
    if re.search(r"licence", document, re.I):
        return re.sub(r"([Ll])icence", r"\1icense", document)
    if re.search(r"license", document, re.I):
        return re.sub(r"([Ll])icense", r"\1icence", document)
    return None


# ponytail: seeded by porting the 27 hand-written company_documents.py keyword lists onto the names
# that exist in TENDER_DOCUMENTS. Values hold only tokens the document name does NOT already contain —
# keywords are concatenated into one BM25 text, which already splits on non-alphanumerics, so "(MOA)"
# and "NEFT/RTGS" tokenize for free. Add a row when a section shows recall misses. Never auto-generate
# acronyms: "Bank Reference Letter" -> "BRL" is noise, not a synonym.
KEYWORD_OVERRIDES: dict[str, list[str]] = {
    "certificate of incorporation": ["COI", "proof of incorporation", "Companies Act registration"],
    "partnership deed": ["registered partnership deed", "Indian Partnership Act", "deed of partnership"],
    "llp agreement": ["LLPIN", "Limited Liability Partnership Agreement", "Form 3 LLP"],
    "memorandum of association moa": ["MOA", "MoA", "memorandum and articles", "object clause"],
    "articles of association aoa": ["AOA", "AoA", "memorandum and articles"],
    "udyam registration certificate": ["MSME Certificate", "Udyog Aadhaar", "micro small medium enterprise"],
    "udyam registration number": ["MSME Certificate", "Udyog Aadhaar", "URN"],
    "msme classification certificate": ["Udyam", "Udyog Aadhaar", "micro small medium enterprise"],
    "startup india certificate": ["DPIIT recognition", "DIPP certificate", "startup exemption"],
    "dpiit startup recognition certificate": ["Startup India", "DIPP certificate", "startup exemption"],
    "shops and establishment registration": ["Gumasta License", "Shops and Establishments Act", "S and E registration"],
    "shops and establishment license": ["Gumasta License", "Shops and Establishments Act", "S and E registration"],
    "trade license": ["municipal trade licence", "corporation trade license"],
    "factory license": ["Factories Act", "Form 4", "factory registration certificate"],
    "import export code iec": ["IEC", "DGFT IEC", "importer exporter code"],
    "iec": ["Import Export Code", "DGFT IEC", "importer exporter code"],
    "import license": ["DGFT licence", "import authorization"],
    "export license": ["DGFT licence", "export authorization"],
    "pan card": ["Permanent Account Number", "PAN copy", "income tax PAN"],
    "company pan card": ["Permanent Account Number", "PAN copy"],
    "company pan": ["Permanent Account Number", "PAN copy"],
    "pan": ["Permanent Account Number", "PAN copy"],
    "tan": ["Tax Deduction Account Number", "TAN allotment letter", "TDS TAN"],
    "gst registration certificate": ["GSTIN", "Form GST REG-06", "goods and services tax registration"],
    "gst registration": ["GSTIN", "Form GST REG-06", "goods and services tax registration"],
    "gst amendment certificate": ["GST REG-15", "amended GST registration", "revised GSTIN certificate"],
    "gst lut": ["Letter of Undertaking", "GST RFD-11", "export without payment of tax"],
    "professional tax registration": ["PTRC", "PTEC", "profession tax enrolment"],
    "epfo registration": ["EPF registration certificate", "Provident Fund registration", "PF code number"],
    "esic registration": ["ESI registration certificate", "Employees State Insurance", "ESIC code number"],
    "labour license": ["CLRA", "Contract Labour Regulation and Abolition Act", "contractor labour licence"],
    "contract labour license": ["CLRA", "Contract Labour Regulation and Abolition Act"],
    "nsic certificate": ["single point registration scheme", "SPRS", "National Small Industries Corporation"],
    "nsic registration": ["single point registration scheme", "SPRS", "National Small Industries Corporation"],
    "quality certifications": ["QMS", "quality assurance certificate", "NABL", "BIS certification"],
    "industry specific license": ["statutory registration", "mandatory licence", "requisite licence"],
}

_MAX_KEYWORDS = 6


def _keywords(document: str) -> list[str]:
    """The document name, its spelling twin, then curated extras. Deduped, order preserved."""
    kws = [document]
    twin = _twin(document)
    if twin:
        kws.append(twin)
    kws += KEYWORD_OVERRIDES.get(_norm(document), [])
    return list(dict.fromkeys(kws))[:_MAX_KEYWORDS]


def _query(document: str) -> str:
    return f"Is submission of {document} required for bid eligibility or compliance in this tender?"


def agent_name(bucket: str, section: str) -> str:
    return f"{bucket}.{section}"


def section_title(agent: str) -> str:
    """'common.gst' -> 'gst'; 'gem_only.gem_registration' -> 'gem registration'."""
    return agent.split(".", 1)[-1].replace("_", " ")


SECTION_QUERIES: dict[str, list[dict]] = {
    agent_name(bucket, section): [
        {"document": document, "query": _query(document), "keywords": _keywords(document)}
        for document in documents
    ]
    for bucket, sections in TENDER_DOCUMENTS.items()
    for section, documents in sections.items()
}

DOCUMENT_AGENTS: tuple[str, ...] = tuple(SECTION_QUERIES)

# single source of "which agents have a fixed checklist" — generate_queries and synthesize both read it
STATIC_QUERIES: dict[str, list[dict]] = {
    "company_document_finder": COMPANY_DOCUMENT_QUERIES,
    **SECTION_QUERIES,
}

_BUCKET_FOR_TYPE = {"gem": "gem_only", "non_gem": "non_gem_only"}
_COMMON_AGENTS = [a for a in DOCUMENT_AGENTS if a.startswith("common.")]


def agents_for_tender_type(tender_type: str | None) -> list[str]:
    """Deterministic routing: the tender type's bucket plus every common section.

    Fails soft. An unknown or missing type returns the common sections alone, which are valid for both
    GeM and non-GeM tenders — missing metadata should cost coverage, never correctness.
    """
    bucket = _BUCKET_FOR_TYPE.get((tender_type or "").strip().lower())
    if not bucket:
        logger.warning("tender_type=%r unknown, running common sections only", tender_type)
        return list(_COMMON_AGENTS)
    return [a for a in DOCUMENT_AGENTS if a.startswith(bucket + ".")] + list(_COMMON_AGENTS)
