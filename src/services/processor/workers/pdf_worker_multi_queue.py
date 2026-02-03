#!/usr/bin/env python3
import uuid
import asyncio
import json
import logging
import os
import io
import aio_pika 
import google.generativeai as genai
from minio import Minio
from pdf2image import convert_from_bytes
from tenacity import retry, stop_after_attempt, wait_exponential

# --- CORRECCIÓN DE IMPORTS ---
# Dockerfile mapea src/shared -> /app/shared
# PYTHONPATH=/app permite importar 'shared' directamente
from shared.vectordb.chunker import EngineeringChunker 
from shared.vectordb.qdrant import QdrantService
from shared.vectordb.client import VectorChunk

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("EngineeringWorkerAsync")

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

class EngineeringWorkerAsync:
    def __init__(self):
        self.rabbitmq_url = os.getenv('RABBITMQ_URL', 'amqp://guest:guest@rabbitmq:5672/')
        
        # Ajuste para usar las variables de entorno correctas de tu docker-compose
        self.minio = Minio(
            os.getenv('MINIO_ENDPOINT', 'minio:9000'),
            access_key=os.getenv('MINIO_USER', 'tutoria_admin'), 
            secret_key=os.getenv('MINIO_PASSWORD', 'TutorIA_Secure_Pass_2024!'), 
            secure=False
        )
        
        self.model = genai.GenerativeModel('gemini-flash-latest')
        self.chunker = EngineeringChunker(chunk_size=1000, chunk_overlap=200)
        
        # Nuestro servicio Qdrant ya es nativo async
        self.qdrant = QdrantService()

    # --- WRAPPERS PARA NO BLOQUEAR EL EVENT LOOP ---

    async def _download_pdf_async(self, bucket, key):
        """Descarga de MinIO en un hilo separado"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.minio.get_object(bucket, key).read())

    async def _render_images_async(self, pdf_bytes):
        """Renderizado de PDF (CPU intensivo) en hilo separado"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: convert_from_bytes(pdf_bytes, dpi=150, fmt='jpeg'))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_gemini_async(self, pil_image):
        """Llamada a Gemini con reintentos automáticos"""
        prompt = """
        Actúa como experto en transcripción LaTeX de Ingeniería. 
        Tu tarea: Transcribe TODO el contenido de esta imagen a formato Markdown.

        Reglas CRÍTICAS:
        1. Ecuaciones en línea usa un solo signo dólar: $ E = mc^2 $
        2. Ecuaciones en bloque usa doble signo dólar: $$ \sum_{i=0}^n x_i $$
        3. Matrices: \\begin{bmatrix}...\\end{bmatrix}
        4. SOLO devuelve el contenido Markdown, sin introducciones.
        """
        loop = asyncio.get_running_loop()
        # Gemini SDK es síncrono, lo envolvemos
        response = await loop.run_in_executor(None, lambda: self.model.generate_content([prompt, pil_image]))
        return response.text

    async def process_message(self, message: aio_pika.IncomingMessage):
        async with message.process():
            data = json.loads(message.body)
            job_id = data.get('job_id')
            logger.info(f"⚡ [Job {job_id}] Iniciando Pipeline Asíncrono...")

            try:
                loop = asyncio.get_running_loop()
                full_markdown = ""
                md_key = f"{job_id}/processed.md"
                md_exists = False

                # --- 0. SMART RESUME: ¿Ya existe el trabajo hecho? ---
                try:
                    logger.info(f"🔎 [Job {job_id}] Buscando backup en MinIO...")
                    # run_in_executor para no bloquear el loop mientras MinIO responde
                    response = await loop.run_in_executor(None, lambda: self.minio.get_object('processed', md_key))
                    full_markdown = response.read().decode('utf-8')
                    response.close()
                    response.release_conn()
                    
                    md_exists = True
                    logger.info(f"♻️ [Job {job_id}] ¡Backup ENCONTRADO! Saltando OCR.")
                except Exception:
                    logger.info(f"🆕 [Job {job_id}] No hay backup. Iniciando OCR desde cero.")
                    md_exists = False

                # --- Si NO existe backup, hacemos el trabajo pesado (Pasos 1-4) ---
                if not md_exists:
                    # 1. Descargar PDF
                    bucket = data.get('minio_bucket', 'uploads')
                    key = data.get('minio_object_key')
                    pdf_data = await self._download_pdf_async(bucket, key)

                    # 2. Renderizar PDF a Imágenes
                    images = await self._render_images_async(pdf_data)

                    # 3. Procesar con Gemini (OCR)
                    for i, img in enumerate(images):
                        logger.info(f"   [Job {job_id}] Vision Pag {i+1}/{len(images)}...")
                        page_md = await self._call_gemini_async(img)
                        full_markdown += f"\n\n\n{page_md}"

                    # 4. Guardar Backup MD en MinIO
                    md_bytes = full_markdown.encode('utf-8')
                    await loop.run_in_executor(None, lambda: self.minio.put_object(
                        'processed', md_key, io.BytesIO(md_bytes), len(md_bytes)
                    ))
                    logger.info(f"💾 Backup guardado en MinIO: {md_key}")

                # --- 5. Chunking (Se ejecuta SIEMPRE) ---
                # Si recuperamos backup, full_markdown ya tiene el texto. Si no, lo acaba de generar Gemini.
                text_chunks = await loop.run_in_executor(None, lambda: self.chunker.split_text(full_markdown))
                
                vector_chunks = []
                for idx, text in enumerate(text_chunks):
                    # --- CORRECCIÓN ID QDRANT ---
                    # Generamos un UUID válido basado en el job_id y el índice
                    # Usamos uuid5 para que sea determinista (mismo input = mismo ID)
                    chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{job_id}_{idx}"))
                    
                    vector_chunks.append(VectorChunk(
                        id=chunk_id,  # <--- Ahora enviamos un UUID real
                        text=text,
                        metadata={
                            "source": data.get('minio_object_key', 'unknown'), 
                            "job_id": job_id,
                            "chunk_index": idx, # Guardamos el índice aquí para saber el orden
                            "filename": data.get("filename", "unknown"),
                            "course_id": data.get("course_id", "general"),
                            "university_id": data.get("university_id", "global"),
                            "doc_type": data.get("doc_type", "notes")
                        }
                    ))

                # --- 6. Indexar en Qdrant ---
                if vector_chunks:
                    logger.info(f"🧠 Insertando {len(vector_chunks)} vectores en Qdrant...")
                    await self.qdrant.upsert_chunks(vector_chunks)

                logger.info(f"✅ [Job {job_id}] FINALIZADO EXITOSAMENTE")

            except Exception as e:
                logger.error(f"🔥 Error fatal procesando Job {job_id}: {e}")
                raise e

    async def run(self):
        """Loop principal del Worker"""
        
        # 1. Asegurar colección Qdrant
        await self.qdrant.ensure_collection()
        
        # 2. Conectar a RabbitMQ
        connection = await aio_pika.connect_robust(self.rabbitmq_url)
        
        async with connection:
            channel = await connection.channel()
            
            # Prefetch count 1 para control de RAM
            await channel.set_qos(prefetch_count=1)
            
            # Declarar cola
            queue = await channel.declare_queue("pdf.process.engineering", durable=True)
            
            logger.info("🚀 Worker Asíncrono ESCUCHANDO mensajes...")
            
            # Empezar a consumir
            await queue.consume(self.process_message)
            
            # Mantener vivo
            await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(EngineeringWorkerAsync().run())
    except KeyboardInterrupt:
        logger.info("🛑 Worker detenido manualmente")