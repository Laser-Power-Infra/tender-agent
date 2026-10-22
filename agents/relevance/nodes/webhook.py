import json
import logging
import urllib.error
import urllib.request
from typing import Any

from lib.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10

# ponytail: company -> env base url (LASER_URL / GMD_URL); missing -> skipped. path fixed per contract
_WEBHOOK_URLS = {
    "laser": lambda: settings.laser_url,
    "gmd": lambda: settings.gmd_url,
}

_WEBHOOK_PATH = "/api/webhook/ai-relevance"


def send_webhook(state: dict[str, Any]) -> dict[str, Any]:
    ref = (state.get("reference_no") or "").strip()
    company = str(state.get("company") or "").lower()
    verdict = state.get("verdict") or {}
    if not ref or not verdict:
        err = "verdict or reference_no missing"
        logger.error(err)
        return {"webhook": {"status": "failed", "error": err}}

    base = (_WEBHOOK_URLS.get(company, lambda: None)() or "").strip()
    if not base:
        logger.info("webhook skipped, no url for company=%s ref=%s", company, ref)
        return {"webhook": {"status": "skipped", "error": None}}
    url = base.rstrip("/") + _WEBHOOK_PATH

    payload = json.dumps(
        {"referenceNo": ref, "company": state.get("company"), "valid": verdict.get("valid"), "reason": verdict.get("reason")}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            logger.info("webhook sent ref=%s company=%s status=%s", ref, company, resp.status)
        return {"webhook": {"status": "sent", "error": None}}
    except (urllib.error.URLError, OSError, ValueError) as e:
        err = f"{type(e).__name__}: {e}"
        # ponytail: non-fatal — verdict already persisted, a failed notification must not rerun the LLM
        logger.error("webhook failed ref=%s company=%s error=%s", ref, company, err)
        return {"webhook": {"status": "failed", "error": err}}