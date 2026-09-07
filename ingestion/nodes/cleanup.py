import logging
from pathlib import Path

from core.config import settings
from ingestion.state import IngestionState

logger = logging.getLogger(__name__)


def cleanup(state: IngestionState) -> dict:
    # ponytail: best-effort unlink only, no rmtree until disk pressure proves need. rmdir only if empty (shared job_id dir)
    file_path = state.get("file_path")
    doc_cache = state.get("doc_cache")
    working_dir = state.get("working_dir")

    try:
        temp_dir = Path(settings.temp_dir).resolve()
    except Exception:
        logger.warning("cleanup skip: temp_dir resolve failed")
        return {}

    def _safe_unlink(p: str | None) -> bool:
        if not p:
            return False
        try:
            path = Path(p).resolve()
            # guard: only delete inside temp_dir
            if temp_dir not in path.parents and path != temp_dir:
                # allow file directly inside temp_dir as well, but check parent
                # strict parent check: path must be inside temp_dir
                try:
                    path.relative_to(temp_dir)
                except ValueError:
                    logger.warning("cleanup skip outside temp_dir path=%s temp=%s", p, temp_dir)
                    return False
            if path.exists() or path.is_symlink():
                path.unlink(missing_ok=True)
                logger.info("cleanup removed %s", path)
                return True
            return False
        except Exception as e:
            logger.warning("cleanup unlink failed path=%s error=%s", p, e)
            return False

    removed_file = _safe_unlink(file_path)
    removed_cache = _safe_unlink(doc_cache)

    # try remove working_dir only if empty and inside temp_dir
    if working_dir:
        try:
            wd = Path(working_dir).resolve()
            try:
                wd.relative_to(temp_dir)
            except ValueError:
                logger.warning("cleanup skip working_dir outside temp_dir wd=%s", wd)
            else:
                if wd.exists() and wd.is_dir():
                    # rmdir only if empty — shared job_id dir safe
                    try:
                        wd.rmdir()
                        logger.info("cleanup removed empty working_dir %s", wd)
                    except OSError:
                        # not empty — expected when multiple docs per job
                        pass
        except Exception as e:
            logger.warning("cleanup working_dir check failed wd=%s error=%s", working_dir, e)

    if not removed_file and not removed_cache:
        logger.info("cleanup nothing to remove file_path=%s doc_cache=%s", file_path, doc_cache)

    return {}
