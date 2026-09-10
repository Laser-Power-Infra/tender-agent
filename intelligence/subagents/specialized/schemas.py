from typing import Literal

from pydantic import BaseModel, Field

from intelligence.subagents.specialized.document_agents import DOCUMENT_AGENTS


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


class ReverseAuctionOutput(BaseModel):
    applicable: bool = Field(description="reverse auction applicable")
    clauses: list[str] = Field(default_factory=list, description="extracted clauses")
    evidence: list[str] = Field(default_factory=list, description="supporting snippets")
    summary: str = Field(default="", description="concise summary")


class EligibilityOutput(BaseModel):
    criteria: list[str] = Field(default_factory=list, description="eligibility criteria")
    evidence: list[str] = Field(default_factory=list, description="supporting snippets")
    summary: str = Field(default="", description="concise summary")


class ImportantDatesOutput(BaseModel):
    dates: list[str] = Field(default_factory=list, description="extracted dates with label")
    evidence: list[str] = Field(default_factory=list, description="supporting snippets")
    summary: str = Field(default="", description="concise summary")


class FinancialTermsOutput(BaseModel):
    terms: list[str] = Field(default_factory=list, description="financial terms EMD payment etc")
    evidence: list[str] = Field(default_factory=list, description="supporting snippets")
    summary: str = Field(default="", description="concise summary")


# ponytail: single source for output schema, agent -> model, like AGENT_PROMPTS.
# The 52 section agents all answer the same question, so they share one model — an empty subclass per
# section would be 52 names for one JSON schema. Give a section its own class when it needs a field.
AGENT_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "company_document_finder": CompanyComplianceOutput,
    "reverse_auction": ReverseAuctionOutput,
    "eligibility": EligibilityOutput,
    "important_dates": ImportantDatesOutput,
    "financial_terms": FinancialTermsOutput,
    **{a: BaseSynthesizeDocumentOutput for a in DOCUMENT_AGENTS},
}
