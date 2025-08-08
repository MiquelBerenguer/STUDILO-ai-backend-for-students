#!/usr/bin/env python3
"""
PDF Processing Worker
Consume mensajes de la cola pdf.process y procesa documentos PDF
"""

import pika
import json
import time
import logging
import os
import sys
from typing import Dict, Any
import traceback

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PDFWorker:
    def __init__(self, rabbitmq_url: str = None):
        """
        Inicializa el worker de procesamiento de PDFs
        
        Args:
            rabbitmq_url: URL de conexión a RabbitMQ
        """
        self.rabbitmq_url = rabbitmq_url or os.getenv(
            'RABBITMQ_URL',
            'amqp://tutor_user:tutor_password@localhost:5672/tutor_ia'
        )
        self.connection = None
        self.channel = None
        self.consumer_tag = None
        
    def connect(self):
        """Establece conexión con RabbitMQ"""
        try:
            parameters = pika.URLParameters(self.rabbitmq_url)
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            
            # Configurar QoS - procesar 1 mensaje a la vez
            self.channel.basic_qos(prefetch_count=1)
            
            logger.info("✅ Conectado a RabbitMQ")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a RabbitMQ: {e}")
            return False
    
    def process_pdf(self, pdf_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa un archivo PDF (aquí iría la lógica real de OCR)
        
        Args:
            pdf_data: Datos del PDF a procesar
            
        Returns:
            Resultado del procesamiento
        """
        logger.info(f"📄 Procesando PDF: {pdf_data.get('filename', 'unknown')}")
        
        # Simulación de procesamiento pesado
        processing_time = pdf_data.get('pages', 1) * 0.5  # 0.5 segundos por página
        time.sleep(processing_time)
        
        # TODO: Aquí iría la lógica real:
        # 1. Descargar PDF de MinIO/S3
        # 2. Ejecutar OCR con Tesseract
        # 3. Extraer texto y metadata
        # 4. Guardar resultados en base de datos
        # 5. Enviar a cola de embeddings si es necesario
        
        result = {
            'status': 'completed',
            'filename': pdf_data.get('filename'),
            'pages': pdf_data.get('pages', 1),
            'text_extracted': f"Texto simulado de {pdf_data.get('pages', 1)} páginas",
            'processing_time': processing_time,
            'worker_id': os.getpid()
        }
        
        logger.info(f"✅ PDF procesado en {processing_time}s")
        return result
    
    def on_message(self, channel, method, properties, body):
        """
        Callback para procesar mensajes de la cola
        
        Args:
            channel: Canal de RabbitMQ
            method: Método de entrega
            properties: Propiedades del mensaje
            body: Cuerpo del mensaje
        """
        try:
            # Decodificar mensaje
            message = json.loads(body)
            logger.info(f"📨 Mensaje recibido: {message.get('job_id', 'unknown')}")
            
            # Procesar PDF
            result = self.process_pdf(message)
            
            # Actualizar estado en base de datos
            self.update_job_status(message.get('job_id'), result)
            
            # Confirmar mensaje procesado
            channel.basic_ack(delivery_tag=method.delivery_tag)
            logger.info(f"✅ Mensaje confirmado: {method.delivery_tag}")
            
            # Si necesita análisis de IA, enviar a siguiente cola
            if message.get('require_analysis', False):
                self.send_to_analysis_queue(message, result)
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error decodificando mensaje: {e}")
            # Rechazar mensaje y enviarlo a DLQ
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            
        except Exception as e:
            logger.error(f"❌ Error procesando mensaje: {e}")
            logger.error(traceback.format_exc())
            
            # Decidir si reintentar o enviar a DLQ
            retry_count = properties.headers.get('x-retry-count', 0) if properties.headers else 0
            
            if retry_count < 3:
                # Reintentar con delay
                self.retry_message(channel, method, properties, body, retry_count)
            else:
                # Enviar a Dead Letter Queue
                logger.error(f"🚫 Mensaje enviado a DLQ después de {retry_count} reintentos")
                channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    
    def retry_message(self, channel, method, properties, body, retry_count):
        """Reintenta procesar un mensaje con delay exponencial"""
        retry_count += 1
        delay = min(300, 10 * (2 ** retry_count))  # Max 5 minutos
        
        logger.warning(f"🔄 Reintentando mensaje (intento {retry_count}) con delay de {delay}s")
        
        # Crear headers con contador de reintentos
        headers = properties.headers or {}
        headers['x-retry-count'] = retry_count
        
        # Publicar mensaje con delay
        channel.basic_publish(
            exchange='tutor.processing',
            routing_key='pdf.process.retry',
            body=body,
            properties=pika.BasicProperties(
                headers=headers,
                expiration=str(delay * 1000)  # TTL en milisegundos
            )
        )
        
        # Confirmar mensaje original
        channel.basic_ack(delivery_tag=method.delivery_tag)
    
    def update_job_status(self, job_id: str, result: Dict[str, Any]):
        """Actualiza el estado del trabajo en la base de datos"""
        # TODO: Implementar actualización en PostgreSQL
        logger.info(f"📊 Actualizando estado del job {job_id}: {result['status']}")
    
    def send_to_analysis_queue(self, original_message: Dict, processing_result: Dict):
        """Envía el resultado a la cola de análisis de IA"""
        analysis_message = {
            'job_id': original_message.get('job_id'),
            'text': processing_result.get('text_extracted'),
            'metadata': {
                'filename': original_message.get('filename'),
                'pages': original_message.get('pages'),
                'processing_time': processing_result.get('processing_time')
            }
        }
        
        self.channel.basic_publish(
            exchange='tutor.direct',
            routing_key='analysis',
            body=json.dumps(analysis_message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Mensaje persistente
                content_type='application/json'
            )
        )
        logger.info(f"📤 Enviado a cola de análisis: {original_message.get('job_id')}")
    
    def start_consuming(self):
        """Inicia el consumo de mensajes"""
        if not self.channel:
            logger.error("❌ No hay conexión establecida")
            return
        
        try:
            # Configurar consumer
            queue_name = 'pdf.process'
            self.consumer_tag = self.channel.basic_consume(
                queue=queue_name,
                on_message_callback=self.on_message,
                auto_ack=False  # ACK manual para confirmar procesamiento
            )
            
            logger.info(f"🎯 Worker escuchando cola: {queue_name}")
            logger.info("👷 Worker iniciado. Presiona CTRL+C para detener...")
            
            # Iniciar consumo
            self.channel.start_consuming()
            
        except KeyboardInterrupt:
            logger.info("🛑 Deteniendo worker...")
            self.stop_consuming()
        except Exception as e:
            logger.error(f"❌ Error en el worker: {e}")
            self.stop_consuming()
    
    def stop_consuming(self):
        """Detiene el consumo de mensajes de forma limpia"""
        if self.channel and self.consumer_tag:
            try:
                self.channel.stop_consuming()
                self.channel.cancel()
                logger.info("✅ Consumo detenido")
            except Exception as e:
                logger.error(f"Error deteniendo consumo: {e}")
        
        if self.connection and not self.connection.is_closed:
            self.connection.close()
            logger.info("🔌 Conexión cerrada")

def main():
    """Función principal del worker"""
    worker = PDFWorker()
    
    # Reintentar conexión si falla
    max_retries = 5
    retry_delay = 5
    
    for attempt in range(max_retries):
        if worker.connect():
            worker.start_consuming()
            break
        else:
            if attempt < max_retries - 1:
                logger.warning(f"⏳ Reintentando conexión en {retry_delay}s... (intento {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2  # Backoff exponencial
            else:
                logger.error("❌ No se pudo conectar después de múltiples intentos")
                sys.exit(1)

if __name__ == "__main__":
    main()