"""Self-check: job_events emits exactly one signed event per job, only to the job's client.

Needs no DB or network: the subscriber lookup is stubbed and a local http.server receives.

Run: uv run python -m tests.test_webhook_dispatch
"""
import http.server
import json
import os
import threading

for _k, _v in {
    "DATABASE_URL": "postgresql://u:p@localhost:5432/d",
    "QDRANT_URL": "http://localhost:9001",
    "QDRANT_API_KEY": "x",
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672",
    "TEMP_DIR": "./tmp",
}.items():
    os.environ.setdefault(_k, _v)

from lib.core import webhook_dispatch as wd  # noqa: E402

SECRET = "whsec_test"
received: list[dict] = []
status_queue: list[int] = []  # statuses to answer with, in order; default 200


class Receiver(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        received.append({"headers": dict(self.headers), "body": body})
        self.send_response(status_queue.pop(0) if status_queue else 200)
        self.end_headers()

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Receiver)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{server.server_port}/hook"

# Stub DB lookup: client "whk_a" subscribes to relevance.analyzed_* only.
SUBS = {("whk_a", "relevance.analyzed_success"), ("whk_a", "relevance.analyzed_failed")}
wd._subscribers = lambda client_id, event: [(URL, client_id, SECRET)] if (client_id, event) in SUBS else []
wd.BACKOFF_S = (0, 0)


def run(fn, client_id="whk_a"):
    received.clear()
    try:
        with wd.job_events("relevance.analyzed", client_id, reference_no="R1") as outcome:
            fn(outcome)
    except RuntimeError:
        pass
    return [json.loads(r["body"]) for r in received]


def main() -> None:
    # success
    [evt] = run(lambda o: o.succeed({"valid": True}))
    assert evt["event"] == "relevance.analyzed_success", evt
    assert evt["data"] == {"reference_no": "R1", "result": {"valid": True}, "error": None}, evt

    # signature verifies with the secret
    h = received[0]["headers"]
    assert h["X-Webhook-Client-Id"] == "whk_a"
    assert h["X-Webhook-Signature"] == wd.sign(SECRET, h["X-Webhook-Timestamp"], received[0]["body"])

    # explicit failure keeps partial result
    [evt] = run(lambda o: o.fail("boom", {"valid": None}))
    assert evt["event"] == "relevance.analyzed_failed" and evt["data"]["error"] == "boom", evt

    # exception anywhere -> failed, and it is re-raised
    def explode(o):
        raise RuntimeError("qdrant down")
    [evt] = run(explode)
    assert evt["data"]["error"] == "RuntimeError: qdrant down", evt
    raised = False
    try:
        with wd.job_events("relevance.analyzed", None):
            raise RuntimeError("x")
    except RuntimeError:
        raised = True
    assert raised

    # early exit without an outcome -> failed
    [evt] = run(lambda o: None)
    assert evt["event"] == "relevance.analyzed_failed" and evt["data"]["error"] == "job ended without a result"

    # routing: other client, no client, unsubscribed event -> nothing sent
    assert run(lambda o: o.succeed(), client_id="whk_other") == []
    assert run(lambda o: o.succeed(), client_id=None) == []
    received.clear()
    wd.emit("whk_a", "relevance.feedback_success", {})
    assert received == []

    # 500 is retried, 400 is not
    status_queue[:] = [500, 200]
    assert len(run(lambda o: o.succeed())) == 2
    status_queue[:] = [400]
    assert len(run(lambda o: o.succeed())) == 1

    # dead receiver never raises
    wd._subscribers = lambda client_id, event: [("http://127.0.0.1:1/none", client_id, SECRET)]
    wd.emit("whk_a", "relevance.analyzed_success", {})

    # unknown event never raises either
    wd.emit("whk_a", "nope", {})
    print("ok")


if __name__ == "__main__":
    main()
