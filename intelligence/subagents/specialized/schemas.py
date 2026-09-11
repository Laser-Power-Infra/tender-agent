from typing import Literal

from pydantic import BaseModel, Field


class DocumentItem(BaseModel):
    name: str = Field(description="document name")
    required: bool = Field(description="true if mandatory")
    evidence: str = Field(description="supporting snippet or clause")


class SynthesisResult(BaseModel):
    summary: str = Field(description="concise answer for task")
    findings: list[str] = Field(default_factory=list, description="key findings")
    evidence: list[str] = Field(default_factory=list, description="supporting evidence snippets")
    documents: list[DocumentItem] = Field(default_factory=list, description="accumulated documents with required flag")


# ponytail: base synthesize document structure per schema {document, required enum, found, evidence, confidence}, extended by company
class BaseSynthesizeDocumentItem(BaseModel):
    document: str = Field(description="exact checklist name")
    required: Literal["Required", "Not Required", "Conditional", "Unclear"] = Field(description="requirement status")
    found: str = Field(description="source_file, page <n> or Not found")
    evidence: str = Field(description="short paraphrase <25 words")
    confidence: Literal["High", "Medium", "Low"] = Field(description="how directly text addresses doc")
    model_config = {"extra": "forbid"}


class BaseSynthesizeDocumentOutput(BaseModel):
    results: list[BaseSynthesizeDocumentItem] = Field(description="array of synthesize document items")


class CompanyComplianceOutput(BaseSynthesizeDocumentOutput):
    pass


class DocumentFinderOutput(CompanyComplianceOutput):
    pass


# ponytail: per-param evidence base — 1 evidence per agent, not per field. Upgrade to per-param EvidenceField if field-level audit needed
class Evidence(BaseModel):
    output: str = Field(default="", description="extracted output snippet")
    found_document: str = Field(default="", description="source file name")
    documentId: str = Field(default="", description="externalId from metadata")
    pageNo: int = Field(default=0, description="page number")


class ReverseAuctionOutput(BaseModel):
    # usable output
    applicable: bool = Field(description="reverse auction applicable")
    clauses: list[str] = Field(default_factory=list, description="extracted clauses")
    summary: str = Field(default="", description="concise summary")
    # base evidence
    evidence: Evidence = Field(default_factory=Evidence, description="grounding evidence")


class BasicDetailsOutput(BaseModel):
    title: str = Field(default="", description="tender title")
    reference_no: str = Field(default="", description="tender reference")
    organization: str = Field(default="", description="issuing organization")
    eligibility: list[str] = Field(default_factory=list, description="eligibility criteria")
    important_dates: list[str] = Field(default_factory=list, description="key dates")
    summary: str = Field(default="", description="concise summary")
    evidence: Evidence = Field(default_factory=Evidence, description="grounding evidence")


class EMDAgentOutput(BaseModel):
    emdAmount: str = Field(default="", description="EMD amount")
    emdPaymentMode: str = Field(default="", description="BG/online/draft")
    emdExemption: list[str] = Field(default_factory=list, description="exemption MSE/Startup/NSIC")
    emdValidity: str = Field(default="", description="EMD validity")
    summary: str = Field(default="", description="concise summary")
    evidence: Evidence = Field(default_factory=Evidence, description="grounding evidence")


class GemDocumentOutput(BaseModel):
    documents: list[str] = Field(default_factory=list, description="gem documents required")
    summary: str = Field(default="", description="concise summary")
    evidence: Evidence = Field(default_factory=Evidence, description="grounding evidence")


class NonGemDocumentOutput(BaseModel):
    documents: list[str] = Field(default_factory=list, description="non-gem documents required")
    summary: str = Field(default="", description="concise summary")
    evidence: Evidence = Field(default_factory=Evidence, description="grounding evidence")


class CommonDocumentOutput(BaseModel):
    documents: list[str] = Field(default_factory=list, description="common documents required")
    summary: str = Field(default="", description="concise summary")
    evidence: Evidence = Field(default_factory=Evidence, description="grounding evidence")


# ponytail: single source for output schema, agent -> model
AGENT_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "document_finder": DocumentFinderOutput,
    "company_document_finder": CompanyComplianceOutput,  # alias — keep file, not in flow
    "reverse_auction": ReverseAuctionOutput,
    "basic_details": BasicDetailsOutput,
    "emd_agent": EMDAgentOutput,
    "gem_document_agent": GemDocumentOutput,
    "non_gem_document_agent": NonGemDocumentOutput,
    "common_document_agent": CommonDocumentOutput,
}
