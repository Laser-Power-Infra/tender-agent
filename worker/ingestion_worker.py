import json
import logging

import pika
from pydantic import ValidationError

from core.config import settings
from ingestion.graph import build_ingestion_graph
from worker.job import IngestionJob

QUEUE_NAME="agent:ingestion"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

logger = logging.getLogger(__name__)

# ponytail: postgres checkpointer, sync PostgresSaver via from_conn_string; setup once, single instance
# ponytail: fallback to no checkpointer if DB unavailable or lib missing, worker still runs
def _init_checkpointer():
    try:
        from langgraph.checkpoint.postgres import PostgresSaver

        uri = settings.database_url
        # normalize postgresql+psycopg:// -> postgresql:// for psycopg driver used by checkpointer
        if uri.startswith("postgresql+psycopg://"):
            uri = uri.replace("postgresql+psycopg://", "postgresql://", 1)
        elif uri.startswith("postgres+psycopg://"):
            uri = uri.replace("postgres+psycopg://", "postgresql://", 1)
        # from_conn_string handles autocommit=True, row_factory=dict_row per docs
        cp = PostgresSaver.from_conn_string(uri)
        cp.setup()  # ponytail: idempotent migrations, must call once before compile
        logger.info("Postgres checkpointer ready")
        return cp
    except Exception as e:
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


def handle_message(ch, method, properties, body):
    logger.info("Received raw body=%r", body)
    try:
        payload = json.loads(body)
        logger.info("Payload parsed: %r", payload)
        job = IngestionJob.model_validate(payload)
        logger.info("Validated job job_id=%s reference_no=%s files=%s", job.job_id, job.reference_no, len(job.files))
        for state in job.to_file_states():  # ponytail: sequential per-file, parallel fan-out if throughput matters
            logger.info("Invoking graph job_id=%s payload=%r", job.job_id, state)
            # ponytail: thread_id = job_id:document_id or external id for resumable checkpoints per doc
            # ponytail: single thread_id per file, avoids cross-file checkpoint collision
            tid = f"{job.job_id}:{state.get('external_document_id') or state.get('file_url')}"
            config = {"configurable": {"thread_id": tid}}
            result = _graph.invoke(state, config=config) if _checkpointer else _graph.invoke(state)
            logger.info("Graph result job_id=%s status=%s file_path=%s error=%s", job.job_id, result.get("status"), result.get("file_path"), result.get("error"))
            if result.get("status") == "failed":
                logger.error("Job %s failed file=%s error=%s", job.job_id, state.get("file_url"), result.get("error"))
                _safe_ack_nack(ch, method, ack=False)
                return
            logger.info("Job %s file done: %s -> %s", job.job_id, result.get("status"), result.get("file_path"))
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
        queue=QUEUE_NAME,
        durable=True
    )

    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=handle_message)

    logger.info("Connected to RabbitMQ")
    logger.info("Waititing for jobs on: %s", QUEUE_NAME)

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