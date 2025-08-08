#!/usr/bin/env python3
"""
RabbitMQ Setup Script
Crea automáticamente las colas, exchanges y bindings necesarios para el sistema Tutor IA
"""

import pika
import json
import os
import sys
from typing import Dict, List, Any
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RabbitMQSetup:
    def __init__(self, connection_url: str = None):
        """
        Inicializa la conexión con RabbitMQ
        
        Args:
            connection_url: URL de conexión en formato amqp://user:pass@host:port/vhost
        """
        self.connection_url = connection_url or os.getenv(
            'RABBITMQ_URL', 
            'amqp://tutor_user:tutor_password@localhost:5672/tutor_ia'
        )
        self.connection = None
        self.channel = None
        
    def connect(self):
        """Establece conexión con RabbitMQ"""
        try:
            parameters = pika.URLParameters(self.connection_url)
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            logger.info("✅ Conexión establecida con RabbitMQ")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a RabbitMQ: {e}")
            return False
    
    def create_exchanges(self):
        """Crea los exchanges necesarios"""
        exchanges = [
            {
                'name': 'tutor.processing',
                'type': 'topic',
                'durable': True,
                'auto_delete': False
            },
            {
                'name': 'tutor.direct',
                'type': 'direct',
                'durable': True,
                'auto_delete': False
            },
            {
                'name': 'tutor.dlx',
                'type': 'topic',
                'durable': True,
                'auto_delete': False
            }
        ]
        
        for exchange in exchanges:
            try:
                self.channel.exchange_declare(
                    exchange=exchange['name'],
                    exchange_type=exchange['type'],
                    durable=exchange['durable'],
                    auto_delete=exchange['auto_delete']
                )
                logger.info(f"✅ Exchange creado: {exchange['name']}")
            except Exception as e:
                logger.warning(f"⚠️  Exchange {exchange['name']} ya existe o error: {e}")
    
    def create_queues(self):
        """Crea las colas con sus configuraciones"""
        queues = [
            {
                'name': 'pdf.process',
                'durable': True,
                'arguments': {
                    'x-message-ttl': 3600000,  # 1 hora
                    'x-dead-letter-exchange': 'tutor.dlx',
                    'x-dead-letter-routing-key': 'pdf.failed',
                    'x-max-length': 10000,
                    'x-max-priority': 5
                }
            },
            {
                'name': 'pdf.process.priority',
                'durable': True,
                'arguments': {
                    'x-message-ttl': 1800000,  # 30 minutos
                    'x-dead-letter-exchange': 'tutor.dlx',
                    'x-dead-letter-routing-key': 'pdf.failed.priority',
                    'x-max-length': 1000,
                    'x-max-priority': 10
                }
            },
            {
                'name': 'ai.embeddings',
                'durable': True,
                'arguments': {
                    'x-message-ttl': 3600000,  # 1 hora
                    'x-dead-letter-exchange': 'tutor.dlx',
                    'x-dead-letter-routing-key': 'ai.embeddings.failed',
                    'x-max-length': 50000
                }
            },
            {
                'name': 'ai.analysis',
                'durable': True,
                'arguments': {
                    'x-message-ttl': 1800000,  # 30 minutos
                    'x-dead-letter-exchange': 'tutor.dlx',
                    'x-dead-letter-routing-key': 'ai.analysis.failed',
                    'x-max-length': 5000
                }
            },
            {
                'name': 'notifications',
                'durable': True,
                'arguments': {
                    'x-message-ttl': 300000,  # 5 minutos
                    'x-max-length': 100000
                }
            },
            {
                'name': 'dlx.failed',
                'durable': True,
                'arguments': {
                    'x-message-ttl': 604800000,  # 7 días
                    'x-max-length': 50000,
                    'x-queue-mode': 'lazy'  # Para colas grandes
                }
            }
        ]
        
        for queue in queues:
            try:
                self.channel.queue_declare(
                    queue=queue['name'],
                    durable=queue['durable'],
                    arguments=queue.get('arguments', {})
                )
                logger.info(f"✅ Cola creada: {queue['name']}")
            except Exception as e:
                logger.warning(f"⚠️  Cola {queue['name']} ya existe o error: {e}")
    
    def create_bindings(self):
        """Crea los bindings entre exchanges y colas"""
        bindings = [
            {
                'queue': 'pdf.process',
                'exchange': 'tutor.processing',
                'routing_key': 'pdf.process'
            },
            {
                'queue': 'pdf.process.priority',
                'exchange': 'tutor.processing',
                'routing_key': 'pdf.process.priority'
            },
            {
                'queue': 'ai.embeddings',
                'exchange': 'tutor.direct',
                'routing_key': 'embeddings'
            },
            {
                'queue': 'ai.analysis',
                'exchange': 'tutor.direct',
                'routing_key': 'analysis'
            },
            {
                'queue': 'notifications',
                'exchange': 'tutor.direct',
                'routing_key': 'notify'
            },
            {
                'queue': 'dlx.failed',
                'exchange': 'tutor.dlx',
                'routing_key': '#'  # Acepta todos los routing keys
            }
        ]
        
        for binding in bindings:
            try:
                self.channel.queue_bind(
                    queue=binding['queue'],
                    exchange=binding['exchange'],
                    routing_key=binding['routing_key']
                )
                logger.info(f"✅ Binding creado: {binding['queue']} -> {binding['exchange']} [{binding['routing_key']}]")
            except Exception as e:
                logger.warning(f"⚠️  Binding {binding['queue']} -> {binding['exchange']} error: {e}")
    
    def setup_all(self):
        """Ejecuta todo el setup"""
        if not self.connect():
            logger.error("❌ No se pudo conectar a RabbitMQ")
            return False
        
        try:
            logger.info("🚀 Iniciando configuración de RabbitMQ...")
            
            # Crear exchanges
            logger.info("📦 Creando exchanges...")
            self.create_exchanges()
            
            # Crear colas
            logger.info("📬 Creando colas...")
            self.create_queues()
            
            # Crear bindings
            logger.info("🔗 Creando bindings...")
            self.create_bindings()
            
            logger.info("✅ Configuración completada exitosamente!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error durante la configuración: {e}")
            return False
        finally:
            if self.connection:
                self.connection.close()
                logger.info("🔌 Conexión cerrada")

def main():
    """Función principal"""
    # Obtener URL de conexión de variables de entorno o usar default
    rabbitmq_url = os.getenv('RABBITMQ_URL')
    
    if not rabbitmq_url:
        # Construir URL desde variables individuales
        user = os.getenv('RABBITMQ_USER', 'tutor_user')
        password = os.getenv('RABBITMQ_PASSWORD', 'tutor_password')
        host = os.getenv('RABBITMQ_HOST', 'localhost')
        port = os.getenv('RABBITMQ_PORT', '5672')
        vhost = os.getenv('RABBITMQ_VHOST', 'tutor_ia')
        
        rabbitmq_url = f"amqp://{user}:{password}@{host}:{port}/{vhost}"
    
    logger.info(f"🔗 Conectando a RabbitMQ...")
    
    setup = RabbitMQSetup(rabbitmq_url)
    success = setup.setup_all()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()