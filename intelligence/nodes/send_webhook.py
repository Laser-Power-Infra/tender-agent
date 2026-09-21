"""Notify an external system when the final result is ready.

Optional node: no TED_WEBHOOK_URL env var means skip. A failed PATCH is logged, never a pipeline
failure — the final_response is already computed and the webhook is a notification, not part of
the answer.
"""
import json
import logging
import urllib.error
import urllib.request

from core.config import settings
from intelligence.state import IntelligenceState

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10


def send_webhook(state: IntelligenceState) -> dict:
    reference_no = (state.get("reference_no") or "").strip()
    final_response = state.get("final_response") or {}

    url = (settings.ted_webhook_url or "").strip()
    if not url:
        logger.info("webhook skipped, TED_WEBHOOK_URL not set ref=%s", reference_no)
        return {"webhook": {"status": "skipped", "error": None}}

    if not reference_no:
        logger.warning("webhook skipped, reference_no missing")
        return {"webhook": {"status": "skipped", "error": "reference_no missing"}}

    payload = json.dumps({"referenceNo": reference_no, "agentReport": json.dumps(final_response)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            logger.info("webhook sent ref=%s status=%s", reference_no, resp.status)
        return {"webhook": {"status": "sent", "error": None}}
    except (urllib.error.URLError, OSError, ValueError) as e:
        err = f"{type(e).__name__}: {e}"
        logger.error("webhook failed ref=%s error=%s", reference_no, err)
        return {"webhook": {"status": "failed", "error": err}}