import functools
import logging
import random
import time

logger = logging.getLogger(__name__)


def _is_429(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) == 429:
        return True
    if getattr(exc, "http_status", None) == 429:
        return True
    # openai.RateLimitError / langchain wrappers
    if "RateLimit" in type(exc).__name__:
        return True
    msg = str(exc).lower()
    if "429" in msg or "too many requests" in msg or "rate limit" in msg:
        return True
    # httpx response attached
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 429:
        return True
    return False


def _retry_after(exc: Exception) -> float | None:
    # try header Retry-After from various wrappers
    for attr in ("response", "http_response", "args"):
        obj = getattr(exc, attr, None)
        if obj is None:
            continue
        # response.headers
        headers = getattr(obj, "headers", None)
        if headers is None and isinstance(obj, tuple) and obj:
            # some wrappers keep response in args[0]
            maybe = obj[0] if hasattr(obj[0], "headers") else None
            headers = getattr(maybe, "headers", None) if maybe else None
        if headers:
            # case-insensitive
            try:
                val = headers.get("retry-after") or headers.get("Retry-After")
                if val is not None:
                    return float(str(val).strip())
            except Exception:
                pass
    # openai error may expose headers dict directly
    hdrs = getattr(exc, "headers", None)
    if isinstance(hdrs, dict):
        try:
            val = hdrs.get("retry-after") or hdrs.get("Retry-After")
            if val is not None:
                return float(str(val).strip())
        except Exception:
            pass
    return None


def retry_on_429(max_retries: int = 5, base: float = 2.0, cap: float = 60.0, jitter: bool = True):
    """
    Retries only on 429/RateLimit. Exponential backoff with jitter. Honors Retry-After.

    Usage:
        from core.retry import retry_on_429

        @retry_on_429(max_retries=5, base=2.0)
        def embed_batch(texts): ...
            return embedder.embed_documents(texts)

        # ponytail: stdlib only, no tenacity. Add async variant when async embeddings needed.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if not _is_429(e):
                        raise
                    if attempt == max_retries:
                        logger.error("retry_on_429 exhausted fn=%s attempts=%s error=%s", fn.__name__, max_retries + 1, e)
                        raise
                    ra = _retry_after(e)
                    if ra is not None:
                        wait = ra
                    else:
                        wait = base * (2**attempt)
                        if jitter:
                            wait += random.uniform(0, 1)
                    wait = min(wait, cap)
                    logger.warning("429 hit fn=%s attempt=%s/%s retry in %.2fs error=%s", fn.__name__, attempt + 1, max_retries + 1, wait, e)
                    time.sleep(wait)
            # should not reach
            if last_exc:
                raise last_exc
            return None

        return wrapper

    return decorator


# ponytail: alias for shorter import, same logic
retry_429 = retry_on_429
