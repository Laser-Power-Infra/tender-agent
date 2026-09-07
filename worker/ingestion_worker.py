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

_graph = build_ingestion_graph()  # ponytail: single compiled graph, restart worker if graph code changes

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
        logger.info("Validated job job_id=%s file_url=%s", job.job_id, job.file_url)
        logger.info("Invoking graph job_id=%s payload=%r", job.job_id, job.to_state())
        result = _graph.invoke(job.to_state())
        logger.info("Graph result job_id=%s status=%s file_path=%s error=%s", job.job_id, result.get("status"), result.get("file_path"), result.get("error"))
        if result.get("status") == "failed":
            logger.error("Job %s failed: %s", job.job_id, result.get("error"))
            _safe_ack_nack(ch, method, ack=False)
            return
        logger.info("Job %s done: %s -> %s", job.job_id, result.get("status"), result.get("file_path"))
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