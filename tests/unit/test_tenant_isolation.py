"""
Unit tests for multi-tenant isolation.

Verifies that queries are properly scoped by store_id to prevent
cross-tenant data leaks.
"""

from __future__ import annotations

import json
import types
import uuid
from unittest.mock import AsyncMock

import pytest

from src.core.product_matcher import MatchQuery, ProductMatcher
from src.services.ai.tool_executor import ToolExecutor


# ---------------------------------------------------------------------------
# ProductMatcher tenant scoping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_product_matcher_passes_store_id():
    """ProductMatcher.find_products passes store_id to vector store search."""
    store_id = uuid.uuid4()
    embedding_service = AsyncMock()
    embedding_service.embed_text.return_value = [0.0] * 1536

    vector_store = AsyncMock()
    vector_store.search.return_value = []

    product_repo = AsyncMock()

    matcher = ProductMatcher(
        embedding_service=embedding_service,
        vector_store=vector_store,
        product_repo=product_repo,
    )

    await matcher.find_products(
        MatchQuery(text="saree"),
        store_id=store_id,
        limit=5,
    )

    vector_store.search.assert_called_once()
    call_kwargs = vector_store.search.call_args[1]
    assert call_kwargs["store_id"] == str(store_id)


@pytest.mark.asyncio
async def test_product_matcher_scopes_vector_follow_up_fetch():
    """Product IDs returned from vector search are re-fetched through the same store scope."""
    store_id = uuid.uuid4()
    product_id = uuid.uuid4()
    embedding_service = AsyncMock()
    embedding_service.embed_text.return_value = [0.0] * 1536

    vector_store = AsyncMock()
    vector_store.search.return_value = [{"product_id": str(product_id), "score": 0.9}]

    product_repo = AsyncMock()
    product_repo.get_by_sku.return_value = None
    product_repo.get_by_ids.return_value = []

    matcher = ProductMatcher(
        embedding_service=embedding_service,
        vector_store=vector_store,
        product_repo=product_repo,
    )

    await matcher.find_products(MatchQuery(text="saree"), store_id=store_id, limit=5)

    product_repo.get_by_ids.assert_called_once_with([product_id], store_id=store_id)


@pytest.mark.asyncio
async def test_product_matcher_sku_lookup_scoped():
    """ProductMatcher passes store_id when doing SKU lookup."""
    store_id = uuid.uuid4()
    embedding_service = AsyncMock()
    vector_store = AsyncMock()
    product_repo = AsyncMock()
    product_repo.get_by_sku.return_value = None

    matcher = ProductMatcher(
        embedding_service=embedding_service,
        vector_store=vector_store,
        product_repo=product_repo,
    )

    await matcher.find_products(
        MatchQuery(text="DMB-2341"),
        store_id=store_id,
        limit=5,
    )

    product_repo.get_by_sku.assert_called_once_with(store_id, "DMB-2341")


# ---------------------------------------------------------------------------
# ToolExecutor tenant scoping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_executor_uses_correct_store_id():
    """ToolExecutor passes its store_id to check_inventory lookups."""
    store_id = uuid.uuid4()
    product_matcher = AsyncMock()
    product_repo = AsyncMock()
    product_repo.get_by_sku.return_value = None

    executor = ToolExecutor(
        product_matcher=product_matcher,
        product_repo=product_repo,
        store_id=store_id,
    )

    await executor.execute("check_inventory", {"sku": "DMB-001"})

    product_repo.get_by_sku.assert_called_once_with(store_id, "DMB-001")


@pytest.mark.asyncio
async def test_tool_executor_search_passes_store_id():
    """ToolExecutor passes store_id to search_products."""
    store_id = uuid.uuid4()
    product_matcher = AsyncMock()
    product_matcher.find_products.return_value = []
    product_repo = AsyncMock()

    executor = ToolExecutor(
        product_matcher=product_matcher,
        product_repo=product_repo,
        store_id=store_id,
    )

    await executor.execute("search_products", {"query": "saree"})

    call_args = product_matcher.find_products.call_args
    assert call_args[0][1] == store_id  # second positional arg is store_id


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_different_store_ids_produce_different_searches():
    """Two ToolExecutors with different store_ids query their own scope."""
    store_a = uuid.uuid4()
    store_b = uuid.uuid4()

    matcher_a = AsyncMock()
    matcher_a.find_products.return_value = []
    matcher_b = AsyncMock()
    matcher_b.find_products.return_value = []

    executor_a = ToolExecutor(product_matcher=matcher_a, product_repo=AsyncMock(), store_id=store_a)
    executor_b = ToolExecutor(product_matcher=matcher_b, product_repo=AsyncMock(), store_id=store_b)

    await executor_a.execute("search_products", {"query": "saree"})
    await executor_b.execute("search_products", {"query": "saree"})

    # Each matcher was called with its own store_id
    assert matcher_a.find_products.call_args[0][1] == store_a
    assert matcher_b.find_products.call_args[0][1] == store_b
