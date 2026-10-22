"""Send job outcomes to registered webhooks.

Wrap a worker job in `job_events(...)`. Every way out of the block (success, failure,
exception, early return) emits exactly one `<base>_success` or `<base>_failed` event.

An event goes only to the webhook whose client_id came with the job, and only if that
webhook is active and subscribed to the event. Jobs without a client_id send nothing.

Receivers verify `X-Webhook-Signature`:
    sha256=hex(HMAC_SHA256(secret, f"{X-Webhook-Timestamp}.{raw_body}"))
"""
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from lib.core.webhook_events import WEBHOOK_EVENTS

logger = logging.getLogger(__name__)

TIMEOUT_S = 10
BACKOFF_S = (2, 5)  # waits between the 3 attempts


class Outcome:
    def __init__(self, ids: dict):
        self.ids = ids
        self.ok: bool | None = None
        self.result = None
        self.error: str | None = None

    def succeed(self, result=None) -> None:
        self.ok, self.result, self.error = True, result, None

    def fail(self, error: str, result=None) -> None:
        self.ok, self.result, self.error = False, result, error


@contextmanager
def job_events(base: str, client_id: str | None, **ids):
    """Emit `<base>_success` / `<base>_failed` to `client_id` when the block exits. Exceptions are re-raised."""
    outcome = Outcome(ids)
    try:
        yield outcome
    except BaseException as e:
        outcome.fail(f"{type(e).__name__}: {e}", outcome.result)
        raise
    finally:
        if outcome.ok is None:
            outcome.fail("job ended without a result", outcome.result)
        emit(
            client_id,
            f"{base}_{'success' if outcome.ok else 'failed'}",
            {**outcome.ids, "result": outcome.result, "error": outcome.error},
        )


def client_id_from(payload: dict) -> str | None:
    return payload.get("client_id") or payload.get("clientId") or None


def _subscribers(client_id: str, event: str) -> list[tuple[str, str, str]]:
    from sqlmodel import select

    from lib.database.connection import get_session_context
    from lib.database.models import Webhook

    with get_session_context() as session:
        rows = session.exec(select(Webhook).where(
            Webhook.client_id == client_id, Webhook.is_active, Webhook.events.any(event)
        )).all()
        return [(w.url, w.client_id, w.secret) for w in rows]


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def _post(url: str, headers: dict, body: bytes) -> None:
    for attempt in range(len(BACKOFF_S) + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                logger.info("Webhook sent event=%s url=%s status=%s", headers["X-Webhook-Event"], url, resp.status)
                return
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                logger.warning("Webhook rejected event=%s url=%s status=%s", headers["X-Webhook-Event"], url, e.code)
                return
            err = f"HTTP {e.code}"
        except Exception as e:
            err = str(e)
        logger.warning("Webhook attempt %s failed event=%s url=%s error=%s", attempt + 1, headers["X-Webhook-Event"], url, err)
        if attempt < len(BACKOFF_S):
            time.sleep(BACKOFF_S[attempt])


def emit(client_id: str | None, event: str, data: dict) -> None:
    """Send one event to the job's webhook if it is active and subscribed. Never raises."""
    # ponytail: synchronous on the worker thread (heartbeat 600s covers retries); move to a delivery queue if subscribers grow
    try:
        if event not in WEBHOOK_EVENTS:
            raise ValueError(f"unknown webhook event {event!r}")
        if not client_id:
            logger.info("No client_id on job, webhook skipped event=%s", event)
            return
        subscribers = _subscribers(client_id, event)
        if not subscribers:
            logger.info("No active subscription client_id=%s event=%s", client_id, event)
            return
        event_id = f"evt_{uuid.uuid4().hex}"
        body = json.dumps(
            {"id": event_id, "event": event, "created_at": datetime.now(timezone.utc).isoformat(), "data": data},
            default=str,
        ).encode()
        for url, client_id, secret in subscribers:
            timestamp = str(int(time.time()))
            _post(url, {
                "Content-Type": "application/json",
                "User-Agent": "tender-agent-webhooks",
                "X-Webhook-Id": event_id,
                "X-Webhook-Event": event,
                "X-Webhook-Client-Id": client_id,
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Signature": sign(secret, timestamp, body),
            }, body)
    except Exception:
        logger.exception("Webhook emit failed event=%s", event)
