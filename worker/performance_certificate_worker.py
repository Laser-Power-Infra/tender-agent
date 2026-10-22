import json
import logging

import pika
from pydantic import ValidationError

from lib.core.config import settings
from lib.core.webhook_dispatch import client_id_from, job_events
from worker.schema.job import PerformanceCertJob

PERFORMANCE_CERT_QUEUE = "agent:performance_cert"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

logger = logging.getLogger(__name__)

_graph = None  # ponytail: singleton, graph compile once


def get_graph():
    global _graph
    if _graph is None:
        from agents.performance_cert.graph import build_performance_cert_graph

        _graph = build_performance_cert_graph()
    return _graph


def connect_rabbitmq() -> pika.BlockingConnection:
    url = settings.rabbitmq_url
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


def _run(ch, method, payload, outcome):
    job = PerformanceCertJob.model_validate(payload)  # base fields gate here; missing -> nack
    state = {
        "job_id": job.job_id,
        "files": [
            {"file_url": f.fileurl, "file_name": f.filename, "file_tag": f.fileTag, "certificate_id": f.performance_certificate_id}
            for f in job.files
        ],
    }
    logger.info("Validated job job_id=%s files=%d", job.job_id, len(job.files))
    result = get_graph().invoke(state)
    if result.get("status") == "failed":
        logger.error("Performance cert job failed ref=%s error=%s", job.job_id, result.get("error"))
        outcome.fail(result.get("error") or "failed", result.get("report"))
    else:
        outcome.succeed(result.get("report"))
    logger.info("Performance cert done ref=%s status=%s", job.job_id, result.get("status"))
    _safe_ack_nack(ch, method, ack=True)


def handle_message(ch, method, properties, body):
    logger.info("Received raw body=%r", body)
    try:
        payload = json.loads(body)
        with job_events(
            "performance_cert.completed",
            client_id_from(payload),
            job_id=payload.get("job_id") or payload.get("jobId") or payload.get("jobID") or payload.get("id"),
        ) as outcome:
            _run(ch, method, payload, outcome)
    except ValidationError as e:
        logger.error("Validation failed body=%r errors=%s", body, e.errors())
        _safe_ack_nack(ch, method, ack=False)
    except Exception:
        logger.exception("Failed to process job body=%r", body)
        _safe_ack_nack(ch, method, ack=False)


def main():
    connection = connect_rabbitmq()
    channel = connection.channel()
    channel.queue_declare(queue=PERFORMANCE_CERT_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=PERFORMANCE_CERT_QUEUE, on_message_callback=handle_message)
    logger.info("Connected to RabbitMQ")
    logger.info("Waititing for jobs on: %s", PERFORMANCE_CERT_QUEUE)
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
