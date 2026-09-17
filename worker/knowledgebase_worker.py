import json
import logging

import pika
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.config import settings
from knowledgebase.graph import build_knowledgebase_graph

KB_QUEUE = "agent:knowledgebase"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

logger = logging.getLogger(__name__)

_graph = build_knowledgebase_graph()  # ponytail: no checkpointer, KB jobs are single-shot


class KnowledgebaseJob(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    mode: str = Field(default="direct", validation_alias=AliasChoices("mode", "type"))
    collection: str | None = Field(default=None, validation_alias=AliasChoices("collection", "collectionName", "collection_name"))
    content: str = Field(validation_alias=AliasChoices("content", "text"))

    @field_validator("content")
    @classmethod
    def check_content(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("content must be non-empty")
        return v


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


def handle_message(ch, method, properties, body):
    logger.info("Received raw body=%r", body)
    try:
        payload = json.loads(body)
        job = KnowledgebaseJob.model_validate(payload)
        state = {"mode": job.mode, "collection": job.collection, "content": job.content}
        logger.info("Invoking kb graph mode=%s collection=%s len=%s", job.mode, job.collection, len(job.content))
        result = _graph.invoke(state)
        if result.get("status") == "failed":
            logger.error("KB job failed collection=%s error=%s", job.collection, result.get("error"))
            _safe_ack_nack(ch, method, ack=False)
            return
        logger.info("KB job done collection=%s vector_id=%s", job.collection, result.get("vector_id"))
        _safe_ack_nack(ch, method, ack=True)
    except ValidationError as e:
        logger.error("Validation failed body=%r errors=%s", body, e.errors())
        _safe_ack_nack(ch, method, ack=False)
    except Exception:
        logger.exception("Failed to process kb job body=%r", body)
        _safe_ack_nack(ch, method, ack=False)


def main():
    connection = connect_rabbitmq()

    channel = connection.channel()

    channel.queue_declare(
        queue=KB_QUEUE,
        durable=True
    )

    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(queue=KB_QUEUE, on_message_callback=handle_message)

    logger.info("Connected to RabbitMQ")
    logger.info("Waiting for jobs on: %s", KB_QUEUE)

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
