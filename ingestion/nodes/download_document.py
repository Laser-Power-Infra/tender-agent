import io
import logging
import re
import json
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

import httpx
from ingestion.state import IngestionState

logger = logging.getLogger(__name__)

# langfuse observability - disabled by default (set LANGFUSE_ENABLED=true to enable)
# kept as dependency for future use, but turned off via env to avoid auth warnings
try:
    from core.config import settings as _lf_settings

    _LANGFUSE_ENABLED = bool(_lf_settings.langfuse_enabled)
except Exception:
    _LANGFUSE_ENABLED = False

if _LANGFUSE_ENABLED:
    try:
        from langfuse import observe, get_client  # type: ignore

        _HAS_LANGFUSE = True
    except ImportError:
        _HAS_LANGFUSE = False

        def observe(*args, **kwargs):  # type: ignore
            def decorator(fn):
                return fn

            if args and callable(args[0]):
                return args[0]
            return decorator

        def get_client():  # type: ignore
            return None
else:
    # commented out / no-op when disabled - re-enable via LANGFUSE_ENABLED=true
    _HAS_LANGFUSE = False

    def observe(*args, **kwargs):  # type: ignore
        def decorator(fn):
            return fn

        if args and callable(args[0]):
            return args[0]
        return decorator

    def get_client():  # type: ignore
        return None

# ---------- google drive helpers ----------

_GDRIVE_PATTERNS = [
    re.compile(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)"),
    re.compile(r"drive\.google\.com/uc\?id=([a-zA-Z0-9_-]+)"),
    re.compile(r"drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)"),
    re.compile(r"docs\.google\.com/(?:document|spreadsheets|presentation|drawings)/d/([a-zA-Z0-9_-]+)"),
]

# google native mime types that require export
_GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
}


def _is_google_drive_url(url: str) -> bool:
    return "drive.google.com" in url or "docs.google.com" in url


def _extract_file_id(url: str) -> str | None:
    # try regex patterns first
    for pat in _GDRIVE_PATTERNS:
        m = pat.search(url)
        if m:
            # folder detection - treat as error later
            if "folders" in pat.pattern:
                return None
            return m.group(1)
    # fallback: query param ?id= or &id=
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        return qs["id"][0]
    # also handle fragment like #...
    return None


def _get_drive_credentials():
    """Load OAuth credentials from 3 env vars (no file dependency).

    Expects env (via core.config.Settings):
      GOOGLE_OAUTH_CLIENT_ID
      GOOGLE_OAUTH_CLIENT_SECRET
      GOOGLE_OAUTH_REFRESH_TOKEN
      GOOGLE_OAUTH_TOKEN_URI (optional, defaults to https://oauth2.googleapis.com/token)

    Uses google.oauth2.credentials.Credentials direct constructor + refresh
    per Context7 docs (/googleapis/google-auth-library-python).
    Returns refreshed Credentials instance.
    Raises ValueError with actionable message if missing/invalid.
    """
    from core.config import settings

    client_id = (settings.google_oauth_client_id or "").strip() if settings.google_oauth_client_id else ""
    client_secret = (settings.google_oauth_client_secret or "").strip() if settings.google_oauth_client_secret else ""
    refresh_token = (settings.google_oauth_refresh_token or "").strip() if settings.google_oauth_refresh_token else ""
    token_uri = (settings.google_oauth_token_uri or "https://oauth2.googleapis.com/token").strip()

    if not client_id or not client_secret or not refresh_token:
        missing = [k for k, v in {"GOOGLE_OAUTH_CLIENT_ID": client_id, "GOOGLE_OAUTH_CLIENT_SECRET": client_secret, "GOOGLE_OAUTH_REFRESH_TOKEN": refresh_token}.items() if not v]
        logger.error("Google Drive env missing: %s (present id=%s secret=%s token=%s)", ", ".join(missing), bool(client_id), bool(client_secret), bool(refresh_token))
        raise ValueError(
            f"Google Drive download requires 3 env vars, missing: {', '.join(missing)}. "
            "Need GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REFRESH_TOKEN. "
            "Create OAuth 2.0 Client ID (Desktop) with drive.readonly scope and generate refresh_token via OAuth flow."
        )

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        # Per Context7: Credentials without scopes uses granted scopes; scope mismatch -> invalid_scope
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
        )  # ponytail: no scopes, use refresh_token granted scopes; set GOOGLE_OAUTH_SCOPES if token limited
        # refresh to obtain access_token (in-memory, no file persistence)
        creds.refresh(Request())

        if not creds.valid:
            raise ValueError("Credentials still invalid after refresh. Re-auth required (refresh_token may be revoked).")

        return creds
    except ValueError:
        raise
    except Exception as e:
        msg = str(e)
        if "invalid_scope" in msg:
            raise ValueError(
                f"Failed to refresh Google OAuth credentials (invalid_scope): {e}. "
                "Refresh token scope mismatch. Regenerate refresh_token with "
                "https://www.googleapis.com/auth/drive.readonly scope (OAuth consent must include it, Desktop client, access_type=offline prompt=consent)."
            ) from e
        raise ValueError(f"Failed to refresh Google OAuth credentials: {e}") from e


def _download_from_gdrive(file_id: str, dest_dir: Path) -> Path:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    creds = _get_drive_credentials()
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    # fetch metadata to decide get vs export
    try:
        meta = service.files().get(fileId=file_id, supportsAllDrives=True, fields="id,name,mimeType,size").execute()
    except Exception as e:
        # provide clearer error for common cases
        msg = str(e)
        if "404" in msg:
            raise FileNotFoundError(f"Google Drive file not found or not shared with OAuth user: {file_id}") from e
        if "403" in msg:
            raise PermissionError(f"Access denied to Drive file {file_id}. Ensure file is shared with OAuth account and drive.readonly scope granted.") from e
        raise

    filename = meta.get("name") or f"{file_id}.bin"
    mime = meta.get("mimeType", "")

    # sanitize filename
    filename = filename.replace("/", "_").replace("\\", "_")
    dest_path = dest_dir / filename

    # choose request type
    if mime in _GOOGLE_EXPORT_MAP:
        export_mime, ext = _GOOGLE_EXPORT_MAP[mime]
        # ensure extension
        if not dest_path.suffix:
            dest_path = dest_path.with_suffix(ext)
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    # chunked download
    fh = io.FileIO(str(dest_path), "wb")
    try:
        downloader = MediaIoBaseDownload(fh, request, chunksize=16 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            # optional: could update langfuse observation with progress
        fh.close()
    except Exception:
        fh.close()
        if dest_path.exists():
            try:
                dest_path.unlink()
            except Exception:
                pass
        raise

    return dest_path


def _download_via_http(url: str, dest_dir: Path) -> Path:
    # derive fallback filename
    parsed = urlparse(url)
    fallback = Path(unquote(parsed.path)).name or "download.bin"
    # strip query
    fallback = fallback.split("?")[0] or "download.bin"
    if not fallback or fallback == "/":
        fallback = "download.bin"

    # try to get filename from headers first via HEAD then GET stream
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(300.0, connect=30.0)) as resp:
        resp.raise_for_status()
        # Content-Disposition
        cd = resp.headers.get("content-disposition", "")
        filename = fallback
        if "filename=" in cd:
            # handle filename*=UTF-8'' and filename="..."
            m = re.search(r'filename\*?="?([^";]+)"?', cd)
            if m:
                filename = unquote(m.group(1).strip().strip('"'))
        # ensure safe
        filename = filename.replace("/", "_").replace("\\", "_")
        dest_path = dest_dir / filename

        # avoid overwrite
        counter = 1
        base = dest_path
        while dest_path.exists():
            dest_path = base.with_name(f"{base.stem}_{counter}{base.suffix}")
            counter += 1

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return dest_path


# ---------- main node ----------

@observe(name="download_document", as_type="span", capture_input=True, capture_output=True)  # type: ignore
def download_document(state: IngestionState) -> dict:
    """
    LangGraph node: downloads file from generic URL or Google Drive (OAuth).
    - Detects Drive URL -> extracts fileId -> uses Drive v3 API with OAuth token.
    - Otherwise uses httpx streaming download.
    Updates state with file_path / status / error. Observable via Langfuse.
    """
    file_url = state.get("file_url")
    working_dir_str = state.get("working_dir")
    client = get_client() if _HAS_LANGFUSE else None

    if not file_url:
        err = "file_url is required in state"
        if client:
            try:
                client.update_current_observation(level="ERROR", status_message=err)  # type: ignore
            except Exception:
                pass
        return {"status": "failed", "error": err}

    if not working_dir_str:
        err = "working_dir is required in state (run initialize_document first)"
        if client:
            try:
                client.update_current_observation(level="ERROR", status_message=err)  # type: ignore
            except Exception:
                pass
        return {"status": "failed", "error": err}

    working_dir = Path(working_dir_str)
    working_dir.mkdir(parents=True, exist_ok=True)

    try:
        # set trace metadata if available
        if client:
            try:
                # attach job/document ids for filtering in Langfuse UI
                meta = {}
                if state.get("job_id"):
                    meta["job_id"] = state["job_id"]
                if state.get("document_id"):
                    meta["document_id"] = state["document_id"]
                if meta:
                    client.update_current_observation(metadata=meta)  # type: ignore
            except Exception:
                pass

        if _is_google_drive_url(file_url):
            file_id = _extract_file_id(file_url)
            if not file_id:
                # check if folder
                if "drive.google.com/drive/folders/" in file_url:
                    raise ValueError("Google Drive folder links are not supported. Provide a file link.")
                raise ValueError(f"Could not extract fileId from Google Drive URL: {file_url}")
            dest = _download_from_gdrive(file_id, working_dir)
        else:
            dest = _download_via_http(file_url, working_dir)

        result = {"file_path": str(dest), "status": "downloaded", "error": None}
        if client:
            try:
                client.update_current_observation(output=result)  # type: ignore
            except Exception:
                pass
        return result

    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        if client:
            try:
                client.update_current_observation(level="ERROR", status_message=err_msg)  # type: ignore
            except Exception:
                pass
        return {"status": "failed", "error": err_msg}
