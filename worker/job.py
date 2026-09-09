from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class IngestionFile(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    filename: str | None = Field(default=None, validation_alias=AliasChoices("filename", "fileName"))
    filetype: str | None = Field(default=None, validation_alias=AliasChoices("filetype", "fileType", "file_type"))
    fileurl: str = Field(validation_alias=AliasChoices("fileurl", "fileUrl", "file_url"))
    fileTag: str = Field(default="", validation_alias=AliasChoices("fileTag", "file_tag", "filetag"))
    external_document_id: int | None = Field(default=None, validation_alias=AliasChoices("external_document_id", "externalDocumentId", "external_documentId", "documentId", "document_id"))

    @field_validator("fileurl")
    @classmethod
    def check_fileurl(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("fileurl must be non-empty")
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("fileurl must start with http:// or https://")
        return v

    @field_validator("fileTag", mode="before")
    @classmethod
    def check_fileTag(cls, v: str | None) -> str:
        if v is None:
            return ""
        if not isinstance(v, str):
            return str(v)
        return v.strip()

    @field_validator("filename", mode="before")
    @classmethod
    def check_filename(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return v
        v = v.strip()
        return v or None

    @field_validator("filetype", mode="before")
    @classmethod
    def check_filetype(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return v
        v = v.strip()
        return v.lower() or None


class IngestionJob(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    job_id: str = Field(validation_alias=AliasChoices("job_id", "jobId", "jobID", "id"))
    reference_no: str = Field(validation_alias=AliasChoices("reference_no", "referenceNo"))
    files: list[IngestionFile]

    @field_validator("job_id")
    @classmethod
    def check_job_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("job_id must be non-empty")
        return v

    @field_validator("reference_no")
    @classmethod
    def check_reference_no(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("referenceNo must be non-empty")
        return v

    @field_validator("files")
    @classmethod
    def check_files(cls, v: list[IngestionFile]) -> list[IngestionFile]:
        if not v:
            raise ValueError("files must be non-empty")
        return v

    def to_state(self) -> dict:
        f = self.files[0]
        return {
            "job_id": self.job_id,
            "file_url": f.fileurl,
            "original_url": f.fileurl,
            "reference_no": self.reference_no,
            "document_tag": f.fileTag,
            "document_name": f.filename,
            "external_document_id": f.external_document_id,
            "status": "pending",
            "error": None,
        }

    def to_file_states(self) -> list[dict]:
        return [
            {
                "job_id": self.job_id,
                "file_url": f.fileurl,
                "original_url": f.fileurl,
                "reference_no": self.reference_no,
                "document_tag": f.fileTag,
                "document_name": f.filename,
                "external_document_id": f.external_document_id,
                "status": "pending",
                "error": None,
            }
            for f in self.files
        ]
