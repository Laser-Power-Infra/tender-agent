from typing import TypedDict


class PerformanceCertState(TypedDict, total=False):
    job_id: str
    files: list[dict]
    unique_files: list[dict]
    duplicates: list[dict]
    pages: list[dict]
    details: list[dict]
    candidates: list[dict]
    aligned: list[dict]
    diffs: list[dict]
    unresolved: list[dict]
    decision: str
    report: dict
    status: str
    error: str | None
