import pika
import json
import uuid

# Configuración de conexión (apuntando a localhost)
# Asegúrate de que estas credenciales coinciden con las de tu docker-compose para RabbitMQ
RABBITMQ_URL = "amqp://tutor_user:tutor_password@localhost:5672/tutor_ia"
QUEUE_NAME = "pdf.process.engineering"

# Datos del trabajo
job_data = {
    "job_id": str(uuid.uuid4()),
    "filename": "test_document.pdf", # <--- ¡ESTO DEBE COINCIDIR CON EL NOMBRE EN MINIO!
    "course_id": "test_101",
    "university_id": "test_uni",
    "minio_bucket": "uploads",
    "minio_object_key": "test_document.pdf" # <--- ¡ESTO TAMBIÉN!
}

try:
    print(f"📡 Conectando a RabbitMQ en localhost...")
    params = pika.URLParameters(RABBITMQ_URL)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    channel.basic_publish(
        exchange='',
        routing_key=QUEUE_NAME,
        body=json.dumps(job_data),
        properties=pika.BasicProperties(
            delivery_mode=2, 
        )
    )

    print(f"✅ ¡ÉXITO! Trabajo enviado. ID: {job_data['job_id']}")
    connection.close()

except Exception as e:
    print(f"❌ Error: {e}")