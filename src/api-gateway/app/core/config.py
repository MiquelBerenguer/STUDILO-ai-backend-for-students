from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "TutorIA API Gateway"
    ENVIRONMENT: str = Field(default="dev", env="ENV")

    # --- Configuración RabbitMQ ---
    # Valores por defecto que COINCIDEN con tu docker-compose.yml
    RABBITMQ_HOST: str = "tutor-ia-rabbitmq" 
    RABBITMQ_PORT: int = 5672
    
    # ¡AQUÍ ESTABA EL ERROR! Cambiamos guest por tutor_user
    RABBITMQ_USER: str = "tutor_user"  
    RABBITMQ_PASS: str = "tutor_password" # Valor default por si falla el .env
    
    # NUEVO: Virtual Host (Vital porque tu RabbitMQ usa 'tutor_ia')
    RABBITMQ_VHOST: str = "tutor_ia" 

    RABBITMQ_CONNECTION_TIMEOUT: int = 10 
    RABBITMQ_MAX_RETRIES: int = 3 
    RABBITMQ_RETRY_BACKOFF: int = 1 

    POSTGRES_SERVER: str = "tutor-ia-postgres-master" # Nombre del servicio en Docker
    POSTGRES_USER: str = "tutor_user"
    POSTGRES_PASSWORD: str = "tutor_password"
    POSTGRES_DB: str = "tutor_ia_db"
    POSTGRES_PORT: int = 5432

    # --- SEGURIDAD (JWT) ---
    # En producción, esto DEBE leerse de una variable de entorno (.env)
    # Genera una segura corriendo en terminal: openssl rand -hex 32
    SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # El token caduca en 30 min
    
    # Tuning del Pool de Conexiones 
    DB_POOL_SIZE: int = 20      # Conexiones base mantenidas
    DB_MAX_OVERFLOW: int = 10   # Conexiones extra para picos

    # --- Topología ---
    EXAM_EXCHANGE_NAME: str = "tutor.exams"
    EXAM_QUEUE_NAME: str = "exam.generate.job"
    EXAM_DLQ_NAME: str = "exam.generate.dlq"
    MESSAGE_TTL_MS: int = 300000 

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()