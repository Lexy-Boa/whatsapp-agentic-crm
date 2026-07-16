"""
Shared fixtures for integration tests that require a real PostgreSQL database.

Tests using the `db_session` fixture hit the Docker Compose Postgres instance.
Each test runs in its own temporary schema so local demo tables in the public
schema are not dropped or mutated by integration tests.

If Postgres is not available, all tests marked with `pytest.mark.db` are skipped.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Import all models so Base.metadata is fully populated
from src.models import Base  # noqa: F401

# Connection string for the Docker Compose Postgres instance
# Use POSTGRES_HOST env var when running inside Docker (service name "postgres"),
# fall back to localhost for running tests from the host machine.
import os

_pg_host = os.environ.get("POSTGRES_HOST", "localhost")
TEST_DB_URL = (
    f"postgresql+asyncpg://crm_user:crm_password@{_pg_host}:5432/fashion_crm"
)


def pytest_collection_modifyitems(config, items):
    """Skip tests marked with @pytest.mark.db if Postgres is unreachable."""
    # Try connecting synchronously at collection time
    import asyncio

    async def _check():
        try:
            engine = create_async_engine(TEST_DB_URL)
            async with engine.connect() as conn:
                await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            await engine.dispose()
            return True
        except Exception:
            return False

    try:
        reachable = asyncio.run(_check())
    except Exception:
        reachable = False

    if not reachable:
        skip_db = pytest.mark.skip(reason="PostgreSQL not available")
        for item in items:
            if "db" in item.keywords:
                item.add_marker(skip_db)


@pytest.fixture
async def db_session():
    """
    Yield an AsyncSession connected to the real Postgres instance.

    Creates all tables in a temporary schema before the test, rolls back the
    transaction after, and drops only that schema during cleanup.
    """
    schema_name = f"test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(TEST_DB_URL, echo=False)
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        execution_options={"schema_translate_map": {None: schema_name}},
    )

    async with admin_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    try:
        # Create all tables in the isolated test schema.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Create a session with a nested transaction for rollback.
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                yield session
                await session.rollback()

    finally:
        await engine.dispose()
        async with admin_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await admin_engine.dispose()
