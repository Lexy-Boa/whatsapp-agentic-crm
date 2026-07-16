from enum import Enum
from functools import lru_cache

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    dev = "dev"
    staging = "staging"
    prod = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    environment: Environment = Environment.dev
    debug: bool = False
    log_level: str = "INFO"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "crm_user"
    postgres_password: str = "crm_password"
    postgres_db: str = "fashion_crm"

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # PostgreSQL pool settings
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    @computed_field
    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_collection: str = Field(default="products", description="Qdrant collection name")

    # Meta WhatsApp Cloud API
    whatsapp_access_token: str = Field(default="", description="Meta Cloud API access token (Bearer)")
    whatsapp_phone_number_id: str = Field(default="", description="Meta Phone Number ID")
    whatsapp_business_account_id: str = Field(default="", description="WhatsApp Business Account ID")
    whatsapp_phone_number: str = Field(default="", description="Store's WhatsApp phone number")
    whatsapp_verify_token: str = Field(default="", description="Token for webhook verification handshake")
    whatsapp_app_secret: str = Field(default="", description="App secret for X-Hub-Signature-256 verification")

    # Claude (Anthropic)
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    claude_model: str = "claude-sonnet-4-6"
    claude_max_tokens: int = 4096
    claude_temperature: float = Field(default=0.7, description="Claude sampling temperature")

    # Store
    store_id: str = Field(default="", description="Default store UUID for this deployment")

    # Shopify
    shopify_api_version: str = Field(default="2024-01", description="Shopify Admin API version")

    # OpenAI (Embeddings only — Whisper moved to Groq)
    openai_api_key: str = Field(default="", description="OpenAI API key for embeddings")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", description="OpenAI embedding model"
    )

    # Groq (Whisper transcription) — https://console.groq.com/
    groq_api_key: SecretStr = Field(default="", description="Groq API key for Whisper")
    whisper_provider: str = Field(default="groq", description="Whisper provider: groq or openai")
    whisper_model: str = "whisper-large-v3"

    # Queue recovery
    queue_processing_timeout_seconds: int = 180
    queue_recovery_interval_seconds: int = 30
    queue_max_recovery_attempts: int = 3

    # WhatsApp outbound policy
    whatsapp_policy_mode: str = Field(default="warn", description="off, warn, or enforce")
    whatsapp_customer_service_window_hours: int = 24

    # CORS
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
