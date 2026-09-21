"""Self-check for IngestionJob content_key: parsing, default, state propagation.

Run: uv run python -m tests.test_ingestion_job
"""
from worker.job import IngestionJob


def _job(**overrides) -> IngestionJob:
    base = {
        "job_id": "j1",
        "reference_no": "R1",
        "files": [{"fileUrl": "https://example.com/a.pdf", "fileTag": "nit"}],
    }
    base.update(overrides)
    return IngestionJob.model_validate(base)


def test_content_key_defaults_to_text():
    assert _job().content_key == "text"


def test_content_key_parses_camel_and_snake():
    assert _job(contentKey="item_name").content_key == "item_name"
    assert _job(content_key="description").content_key == "description"


def test_content_key_empty_rejected():
    try:
        _job(contentKey="   ")
    except Exception:
        pass
    else:
        raise AssertionError("empty content_key must raise")


def test_content_key_flows_to_file_states():
    states = _job(contentKey="item_name").to_file_states()
    assert states[0]["content_key"] == "item_name"
    assert _job().to_file_states()[0]["content_key"] == "text"


if __name__ == "__main__":
    test_content_key_defaults_to_text()
    test_content_key_parses_camel_and_snake()
    test_content_key_empty_rejected()
    test_content_key_flows_to_file_states()
    print("ingestion job content_key self-check passed")