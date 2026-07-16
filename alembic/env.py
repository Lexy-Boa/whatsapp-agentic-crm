import asyncio
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import Base — this triggers all model imports via src/models/__init__.py,
# registering every table with Base.metadata before Alembic inspects it.
from src.models import Base
from src.config import get_settings

# Alembic Config object (provides access to alembic.ini values)
config = context.config

# Set up Python logging from the [loggers] section of alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the placeholder sqlalchemy.url with the real URL from Settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# The MetaData that all models are registered against
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection — outputs SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Create an async engine and run migrations via run_sync.
    NullPool prevents connection pool hangs on process exit.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    # Windows + asyncpg: ProactorEventLoop can cause issues; use SelectorEventLoop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
