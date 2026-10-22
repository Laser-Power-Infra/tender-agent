import faulthandler
import gc
import json
import logging

import pika
from pydantic import ValidationError

from lib.core.config import settings
from lib.core.webhook_dispatch import client_id_from, job_events
from agents.ingestion.graph import build_ingestion_graph
from worker.schema.job import IngestionJob

INGESTION_QUEUE = "agent:ingestion"
INTELLIGENCE_QUEUE = "agent:intelligence"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

# ponytail: dump native fatal-signal traceback (segfault/abort in docling/torch) to stderr.
# Cannot catch OOM SIGKILL; if this prints nothing, the kernel killed the process.
faulthandler.enable()

logger = logging.getLogger(__name__)


def _rss_mb() -> float:
    # ponytail: /proc/self/status VmRSS, no psutil dep. -1 when unreadable (non-linux).
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return -1.0


def _reclaim_memory():
    # ponytail: drop cyclic garbage, then hand glibc arenas back to the OS. Does not shrink
    # torch/onnx/pdfium internal caches — Step 2 shrinks the per-doc peak for those.
    gc.collect()
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


# ponytail: postgres checkpointer, sync PostgresSaver via from_conn_string; setup once, single instance
# ponytail: fallback to no checkpointer if DB unavailable or lib missing, worker still runs
_cp_cm = None  # ponytail: context manager kept open for process lifetime

def _init_checkpointer():
    global _cp_cm
    try:
        from langgraph.checkpoint.postgres import PostgresSaver

        uri = settings.database_url
        # normalize postgresql+psycopg:// -> postgresql:// for psycopg driver used by checkpointer
        if uri.startswith("postgresql+psycopg://"):
            uri = uri.replace("postgresql+psycopg://", "postgresql://", 1)
        elif uri.startswith("postgres+psycopg://"):
            uri = uri.replace("postgres+psycopg://", "postgresql://", 1)
        # from_conn_string is a context manager, not a saver; enter and keep it open for worker lifetime
        _cp_cm = PostgresSaver.from_conn_string(uri)
        cp = _cp_cm.__enter__()
        cp.setup()  # ponytail: idempotent migrations, must call once before compile
        logger.info("Postgres checkpointer ready")
        return cp
    except Exception as e:
        if _cp_cm is not None:
            try:
                _cp_cm.__exit__(None, None, None)
            except Exception:
                pass
            _cp_cm = None
        logger.warning("Checkpointer init failed, running without: %s", e)
        return None

_checkpointer = _init_checkpointer()
_graph = build_ingestion_graph(checkpointer=_checkpointer)  # ponytail: restart worker if graph code changes

def connect_rabbitmq() -> pika.BlockingConnection:
    url = settings.rabbitmq_url
    # heartbeat 600 covers 400s docling, avoid StreamLostError
    sep = "&" if "?" in url else "?"
    if "heartbeat" not in url:
        url = f"{url}{sep}heartbeat=600&blocked_connection_timeout=600"
    parameters = pika.URLParameters(url)
    parameters.heartbeat = 600
    parameters.blocked_connection_timeout = 600
    return pika.BlockingConnection(parameters)


def _safe_ack_nack(ch, method, ack: bool):
    try:
        if ch.is_open:
            if ack:
                ch.basic_ack(delivery_tag=method.delivery_tag)
            else:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        else:
            logger.warning("Channel closed, skip %s delivery_tag=%s", "ack" if ack else "nack", method.delivery_tag)
    except Exception as e:
        logger.warning("Ack/nack failed (connection lost) delivery_tag=%s error=%s", method.delivery_tag, e)


def _publish_intelligence(reference_no: str, tender_type: str = "", client_id: str | None = None):
    # ponytail: was `"GEM" if "gem" in reference_no.lower() else "NON_GEM"` — a substring test that
    # called any reference containing "gem" (GEMINI, NONGEM-…) a GeM tender, and asserted every other
    # reference was definitively non-GeM. The type now comes from the job; "" means unknown, which
    # runs the common documents only.
    payload = json.dumps({"referenceNo": reference_no, "tender_type": tender_type, "client_id": client_id})
    conn = None
    try:
        conn = connect_rabbitmq()
        ch = conn.channel()
        ch.queue_declare(queue=INTELLIGENCE_QUEUE, durable=True)
        ch.basic_publish(exchange="", routing_key=INTELLIGENCE_QUEUE, body=payload.encode(), properties=pika.BasicProperties(delivery_mode=2))
        logger.info("Published intelligence job reference_no=%s tender_type=%s", reference_no, tender_type)
    except Exception as e:
        logger.warning("Intelligence publish failed ref=%s error=%s", reference_no, e)
    finally:
        try:
            if conn and conn.is_open:
                conn.close()
        except Exception:
            pass


def handle_message(ch, method, properties, body):
    logger.info("Received raw body=%r", body)
    try:
        payload = json.loads(body)
        logger.info("Payload parsed: %r", payload)
        client_id = client_id_from(payload)
        with job_events(
            "document.ingested",
            client_id,
            job_id=payload.get("job_id") or payload.get("jobId"),
            reference_no=payload.get("reference_no") or payload.get("referenceNo"),
        ) as outcome:
            job = IngestionJob.model_validate(payload)
            outcome.ids.update(job_id=job.job_id, reference_no=job.reference_no, tender_type=job.tender_type)
            logger.info("Validated job job_id=%s reference_no=%s files=%s", job.job_id, job.reference_no, len(job.files))
            logger.info("RSS job start job_id=%s rss_mb=%.1f", job.job_id, _rss_mb())
            files = []
            outcome.result = {"files": files}  # partial result if a later file raises
            for state in job.to_file_states():  # ponytail: sequential per-file, parallel fan-out if throughput matters
                result = None  # drop prior file's full state before the next invoke so it can be reclaimed
                _reclaim_memory()
                logger.info("Invoking graph job_id=%s payload=%r", job.job_id, state)
                # ponytail: thread_id = job_id:document_id or external id for resumable checkpoints per doc
                # ponytail: single thread_id per file, avoids cross-file checkpoint collision
                tid = f"{job.job_id}:{state.get('external_document_id') or state.get('file_url')}"
                config = {"configurable": {"thread_id": tid}}
                logger.info("RSS before invoke file=%s rss_mb=%.1f", state.get("file_url"), _rss_mb())
                result = _graph.invoke(state, config=config) if _checkpointer else _graph.invoke(state)
                logger.info("Graph result job_id=%s status=%s file_path=%s error=%s rss_mb=%.1f", job.job_id, result.get("status"), result.get("file_path"), result.get("error"), _rss_mb())
                files.append({
                    "document_id": result.get("document_id"),
                    "external_document_id": state.get("external_document_id"),
                    "file_url": state.get("file_url"),
                    "status": result.get("status"),
                    "chunk_count": result.get("chunk_count"),
                    "total_pages": result.get("total_pages"),
                    "error": result.get("error"),
                })
                if result.get("status") == "failed":
                    logger.error("Job %s failed file=%s error=%s", job.job_id, state.get("file_url"), result.get("error"))
                    outcome.fail(f"{state.get('file_url')}: {result.get('error') or 'ingestion failed'}", {"files": files})
                    result = None
                    _reclaim_memory()
                    _safe_ack_nack(ch, method, ack=False)
                    return
                logger.info("Job %s file done: %s -> %s rss_mb=%.1f", job.job_id, result.get("status"), result.get("file_path"), _rss_mb())
            result = None
            _reclaim_memory()
            outcome.succeed({"files": files})
            logger.info("RSS job end job_id=%s rss_mb=%.1f", job.job_id, _rss_mb())
        _publish_intelligence(job.reference_no, job.tender_type, client_id)
        _safe_ack_nack(ch, method, ack=True)
    except ValidationError as e:
        logger.error("Validation failed body=%r errors=%s", body, e.errors())
        _safe_ack_nack(ch, method, ack=False)
    except Exception:
        logger.exception("Failed to process job body=%r", body)
        _safe_ack_nack(ch, method, ack=False)

def main():
    connection = connect_rabbitmq()

    channel = connection.channel()

    channel.queue_declare(
        queue=INGESTION_QUEUE,
        durable=True
    )

    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(queue=INGESTION_QUEUE, on_message_callback=handle_message)

    logger.info("Connected to RabbitMQ")
    logger.info("Waititing for jobs on: %s", INGESTION_QUEUE)

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Stopping worker...")
        try:
            channel.stop_consuming()
        except Exception:
            pass
    finally:
        try:
            if connection.is_open:
                connection.close()
        except Exception as e:
            logger.warning("Connection close failed (already closed): %s", e)


if __name__ == "__main__":
    main()