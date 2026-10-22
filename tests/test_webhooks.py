"""Self-check for the webhook registration API.

Needs the Postgres from .env with migrations applied (`uv run alembic upgrade head`).
Creates one webhook and deletes it again.

Run: uv run python tests/test_webhooks.py
"""
from fastapi.testclient import TestClient

from api.main import app
from lib.core.webhook_events import WEBHOOK_EVENTS

client = TestClient(app)


def main() -> None:
    listed = client.get("/api/webhooks/events").json()
    assert [e["name"] for e in listed] == list(WEBHOOK_EVENTS), listed
    events = list(WEBHOOK_EVENTS)

    bad = client.post("/api/webhooks", json={"name": "x", "url": "https://a.test", "events": ["nope"]})
    assert bad.status_code == 422, bad.text
    empty = client.post("/api/webhooks", json={"name": "x", "url": "https://a.test", "events": []})
    assert empty.status_code == 422, empty.text
    bad_url = client.post("/api/webhooks", json={"name": "x", "url": "not a url", "events": events[:1]})
    assert bad_url.status_code == 422, bad_url.text

    res = client.post(
        "/api/webhooks",
        json={"name": "self-check", "url": "https://a.test/hook", "events": [events[0], events[0], events[1]]},
    )
    assert res.status_code == 201, res.text
    hook = res.json()
    try:
        assert hook["client_id"].startswith("whk_") and hook["secret"].startswith("whsec_"), hook
        assert hook["events"] == events[:2], hook["events"]

        patched = client.patch(f"/api/webhooks/{hook['id']}", json={"is_active": False}).json()
        assert patched["is_active"] is False and patched["events"] == events[:2], patched

        rotated = client.post(f"/api/webhooks/{hook['id']}/rotate-secret").json()
        assert rotated["secret"] != hook["secret"] and rotated["client_id"] == hook["client_id"]
    finally:
        assert client.delete(f"/api/webhooks/{hook['id']}").status_code == 204

    assert client.patch(f"/api/webhooks/{hook['id']}", json={"is_active": True}).status_code == 404
    assert client.get("/webhooks").status_code == 200
    print("ok")


if __name__ == "__main__":
    main()
