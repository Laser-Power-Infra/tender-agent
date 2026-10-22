import json
import logging

import pika
from pydantic import ValidationError

from lib.core.config import settings
from lib.core.webhook_dispatch import client_id_from, job_events
from worker.schema.job import RelevanceJob

RELEVANCE_QUEUE = "agent:relevance"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

logger = logging.getLogger(__name__)

_graph = None  # ponytail: singleton, graph compile once


def get_graph():
    global _graph
    if _graph is None:
        from agents.relevance.graph import build_relevance_graph

        _graph = build_relevance_graph()
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


EVENT_BASE = {"analysis": "relevance.analyzed", "feedback": "relevance.feedback"}


def _run(ch, method, payload, outcome=None):
    job = RelevanceJob.model_validate(payload)  # base fields gate here; missing -> nack
    state = {
        "payload_type": job.payload_type.value,
        "reference_no": job.reference_no,
        "company": job.company.value,
        "category": job.category,
        "tender_amount": job.tender_amount,
        # client_id is routing only; feedback embeds every extra key, so keep it out.
        "extra": {k: v for k, v in (job.model_extra or {}).items() if k not in ("client_id", "clientId")},
    }
    logger.info("Validated job reference_no=%s company=%s payload_type=%s", job.reference_no, job.company, job.payload_type)
    result = get_graph().invoke(state)
    if outcome is not None:
        outcome.ids.update(reference_no=job.reference_no, company=job.company.value)
        is_analysis = job.payload_type.value == "analysis"
        data = result.get("verdict") if is_analysis else {"vector_ids": result.get("vector_ids") or []}
        if result.get("status") == ("analyzed" if is_analysis else "indexed"):
            outcome.succeed(data)
        else:
            outcome.fail(result.get("error") or f"status {result.get('status')!r}", data or None)
    if result.get("status") == "failed":
        logger.error("Relevance job failed ref=%s error=%s", job.reference_no, result.get("error"))
        _safe_ack_nack(ch, method, ack=False)
        return
    logger.info("Relevance done ref=%s type=%s", job.reference_no, job.payload_type)
    _safe_ack_nack(ch, method, ack=True)


def handle_message(ch, method, properties, body):
    logger.info("Received raw body=%r", body)
    try:
        payload = json.loads(body)
        payload_type = payload.get("payload_type") or payload.get("payloadType") or payload.get("type")
        base = EVENT_BASE.get(payload_type)
        if base is None:
            # Unknown type has no event; validation inside _run rejects the job.
            _run(ch, method, payload)
            return
        with job_events(
            base,
            client_id_from(payload),
            reference_no=payload.get("reference_no") or payload.get("referenceNo"),
            company=payload.get("company") or payload.get("companyName"),
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
    channel.queue_declare(queue=RELEVANCE_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=RELEVANCE_QUEUE, on_message_callback=handle_message)
    logger.info("Connected to RabbitMQ")
    logger.info("Waititing for jobs on: %s", RELEVANCE_QUEUE)
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