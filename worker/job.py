from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class IngestionJob(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    job_id: str
    file_url: str = Field(validation_alias=AliasChoices("file_url", "fileUrl", "documentUrl", "document_url", "originalUrl", "original_url"))
    reference_no: str = Field(validation_alias=AliasChoices("reference_no", "referenceNo"))
    document_tag: str = Field(validation_alias=AliasChoices("document_tag", "documentTag"))
    document_name: str | None = Field(default=None, validation_alias=AliasChoices("document_name", "documentName"))

    @field_validator("job_id")
    @classmethod
    def check_job_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("job_id must be non-empty")
        return v

    @field_validator("file_url")
    @classmethod
    def check_file_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("file_url must be non-empty")
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("file_url must start with http:// or https://")
        return v

    @field_validator("reference_no")
    @classmethod
    def check_reference_no(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("referenceNo must be non-empty")
        return v

    @field_validator("document_tag")
    @classmethod
    def check_document_tag(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("documentTag must be non-empty")
        return v

    @field_validator("document_name", mode="before")
    @classmethod
    def check_document_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return v
        v = v.strip()
        return v or None

    def to_state(self) -> dict:
        return {
            "job_id": self.job_id,
            "file_url": self.file_url,
            "original_url": self.file_url,
            "reference_no": self.reference_no,
            "document_tag": self.document_tag,
            "document_name": self.document_name,
            "status": "pending",
            "error": None,
        }
