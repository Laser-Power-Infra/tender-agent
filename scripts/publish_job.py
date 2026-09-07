import argparse
import logging
import sys
from pathlib import Path
from uuid import uuid4

import pika
from pydantic import ValidationError

# ensure project root on path when run as `python scripts/publish_job.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import settings
from worker.job import IngestionJob

QUEUE_NAME = "agent:ingestion"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def publish(document_url: str, job_id: str | None = None, reference_no: str | None = None, document_tag: str | None = None, document_name: str | None = None) -> None:
    job = IngestionJob(
        job_id=job_id or str(uuid4()),
        file_url=document_url,
        reference_no=reference_no or "REF-UNKNOWN",
        document_tag=document_tag or "general",
        document_name=document_name,
    )
    body = job.model_dump_json().encode()
    params = pika.URLParameters(settings.rabbitmq_url)
    conn = pika.BlockingConnection(params)
    try:
        ch = conn.channel()
        ch.queue_declare(queue=QUEUE_NAME, durable=True)
        ch.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
        logger.info("Published job_id=%s file_url=%s -> %s", job.job_id, job.file_url, QUEUE_NAME)
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Publish ingestion job to RabbitMQ")
    p.add_argument("document_url", help="document URL (http/https, Drive link)")
    p.add_argument("--job-id", dest="job_id", default=None, help="optional job_id, default uuid4")
    p.add_argument("--reference-no", dest="reference_no", default=None, help="referenceNo (required, strict)")
    p.add_argument("--tag", dest="document_tag", default=None, help="documentTag (required, strict)")
    p.add_argument("--name", dest="document_name", default=None, help="documentName (optional)")
    args = p.parse_args()
    try:
        publish(args.document_url, args.job_id, args.reference_no, args.document_tag, args.document_name)
    except ValidationError as e:
        logger.error("Validation failed: %s", e.errors())
        sys.exit(2)
    except Exception:
        logger.exception("Publish failed")
        sys.exit(1)


if __name__ == "__main__":
    main()  # ponytail: single job only, add batch loop if bulk test needed
