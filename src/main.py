import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.agent.router import router as agent_router
from src.api.control_room.router import api_router as control_room_api_router
from src.api.control_room.router import ui_router as control_room_ui_router
from src.api.webhooks.whatsapp import router as whatsapp_router
from src.config import Environment, get_settings
from src.db.postgres import close_db, init_db
from src.db.redis_client import close_redis, init_redis

settings = get_settings()


def configure_logging() -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.environment == Environment.prod:
        processors = shared_processors + [structlog.processors.JSONRenderer()]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


configure_logging()
logger = structlog.get_logger(__name__)


def _missing_required_settings(current_settings=settings) -> list[str]:
    """Return required settings that are empty for the current environment."""
    required = {
        "anthropic_api_key": current_settings.anthropic_api_key,
        "whatsapp_access_token": current_settings.whatsapp_access_token,
        "store_id": current_settings.store_id,
        "openai_api_key": current_settings.openai_api_key,
    }
    if current_settings.environment == Environment.prod:
        required["whatsapp_app_secret"] = current_settings.whatsapp_app_secret
    return [name for name, value in required.items() if not value]


def _validate_required_settings() -> None:
    """Validate that required settings are non-empty. Raises SystemExit on failure."""
    missing = _missing_required_settings(settings)
    if missing:
        for name in missing:
            logger.error("missing_required_setting", setting=name)
        raise SystemExit(
            f"Missing required settings: {', '.join(missing)}. "
            "Set them in .env or as environment variables."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("starting_up", environment=settings.environment, version="0.1.0")
    _validate_required_settings()
    await init_db()
    await init_redis()
    logger.info("startup_complete")

    yield

    # Shutdown
    logger.info("shutting_down")
    await close_db()
    await close_redis()
    logger.info("shutdown_complete")


app = FastAPI(
    title="WhatsApp Fashion CRM",
    description="WhatsApp automation for Indian fashion brands with dialect-aware voice transcription",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != Environment.prod else None,
    redoc_url="/redoc" if settings.environment != Environment.prod else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(whatsapp_router)
app.include_router(agent_router)
app.include_router(control_room_api_router)
app.include_router(control_room_ui_router)


@app.get("/health")
async def health_check():
    from src.db.postgres import check_db_health
    from src.db.redis_client import check_redis_health

    db_ok = await check_db_health()
    redis_ok = await check_redis_health()

    status = "healthy" if (db_ok and redis_ok) else "degraded"
    return {
        "status": status,
        "version": "0.1.0",
        "environment": settings.environment,
        "checks": {
            "database": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
    }
