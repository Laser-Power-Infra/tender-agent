import pika
from core.config import settings

QUEUE_NAME="agent:ingestion"

def connect_rabbitmq() -> pika.BlockingConnection:
    parameters = pika.URLParameters(settings.rabbitmq_url)

    return pika.BlockingConnection(parameters)


def handle_message(ch, method, properties, body):
    print(f"Received job: {body}")

    ch.basic_ack(delivery_tab=method.delivery_tag)

def main():
    connection = connect_rabbitmq()

    channel = connection.channel()

    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True
    )

    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=handle_message)

    print(f"Connected to RabbitMQ")
    print(f"Waititing for jobs on: {QUEUE_NAME}")

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("Stopping worker...")
        channel.stop_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    main()