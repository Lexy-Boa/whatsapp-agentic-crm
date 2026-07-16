"""
Unit tests for ToolExecutor.

Each tool's execution is tested in isolation with mocked dependencies.
"""

from __future__ import annotations

import json
import types
import uuid
from unittest.mock import AsyncMock

import pytest

from src.core.product_matcher import ProductMatch
from src.services.ai.tool_executor import ToolExecutor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STORE_ID = uuid.uuid4()


@pytest.fixture
def product_matcher():
    return AsyncMock()


@pytest.fixture
def product_repo():
    return AsyncMock()


@pytest.fixture
def executor(product_matcher, product_repo):
    return ToolExecutor(
        product_matcher=product_matcher,
        product_repo=product_repo,
        store_id=STORE_ID,
    )


# ---------------------------------------------------------------------------
# search_products
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_products_returns_results(executor, product_matcher):
    """search_products returns formatted product list."""
    product = types.SimpleNamespace(
        name="Red Silk Saree",
        sku="DMB-001",
        base_price=12000,
        description="Beautiful red silk saree",
        category="sarees",
        occasions=["wedding"],
        variants=[],
    )
    product_matcher.find_products.return_value = [
        ProductMatch(product=product, score=0.95, match_type="semantic")
    ]

    result = json.loads(await executor.execute("search_products", {"query": "red silk saree"}))

    assert len(result["products"]) == 1
    assert result["products"][0]["name"] == "Red Silk Saree"
    assert result["products"][0]["sku"] == "DMB-001"
    assert result["products"][0]["price"] == 12000


@pytest.mark.asyncio
async def test_search_products_empty(executor, product_matcher):
    """search_products returns empty list when no matches found."""
    product_matcher.find_products.return_value = []

    result = json.loads(await executor.execute("search_products", {"query": "nonexistent"}))

    assert result["products"] == []
    assert "No products found" in result["message"]


@pytest.mark.asyncio
async def test_search_products_with_price_range(executor, product_matcher):
    """search_products passes price range to product matcher."""
    product_matcher.find_products.return_value = []

    await executor.execute("search_products", {
        "query": "saree",
        "price_min": 5000,
        "price_max": 15000,
    })

    call_args = product_matcher.find_products.call_args
    query = call_args[0][0]
    assert query.price_range == (5000.0, 15000.0)


# ---------------------------------------------------------------------------
# check_inventory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_inventory_found(executor, product_repo):
    """check_inventory returns stock info for existing product."""
    product = types.SimpleNamespace(
        name="Kasavu Saree",
        sku="DMB-002",
        variants=[
            types.SimpleNamespace(size="Free Size", color="White", stock_quantity=5),
        ],
    )
    product_repo.get_by_sku.return_value = product

    result = json.loads(await executor.execute("check_inventory", {"sku": "DMB-002"}))

    assert result["in_stock"] is True
    assert result["product"] == "Kasavu Saree"


@pytest.mark.asyncio
async def test_check_inventory_not_found(executor, product_repo):
    """check_inventory returns error for unknown SKU."""
    product_repo.get_by_sku.return_value = None

    result = json.loads(await executor.execute("check_inventory", {"sku": "NOPE-999"}))

    assert "error" in result
    assert "NOPE-999" in result["error"]


@pytest.mark.asyncio
async def test_check_inventory_with_size_filter(executor, product_repo):
    """check_inventory filters variants by size."""
    product = types.SimpleNamespace(
        name="Cotton Saree",
        sku="DMB-003",
        variants=[
            types.SimpleNamespace(size="S", color="Red", stock_quantity=0),
            types.SimpleNamespace(size="M", color="Red", stock_quantity=3),
        ],
    )
    product_repo.get_by_sku.return_value = product

    result = json.loads(await executor.execute("check_inventory", {"sku": "DMB-003", "size": "M"}))

    assert result["in_stock"] is True
    assert len(result["variants"]) == 1
    assert result["variants"][0]["size"] == "M"


# ---------------------------------------------------------------------------
# lookup_order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lookup_order_stub(executor):
    """lookup_order returns a stub message (not yet implemented)."""
    result = json.loads(await executor.execute("lookup_order", {"order_id": "ORD-123"}))

    assert "not yet available" in result["message"]


@pytest.mark.asyncio
async def test_lookup_order_missing_params(executor):
    """lookup_order returns error when no params provided."""
    result = json.loads(await executor.execute("lookup_order", {}))

    assert "error" in result


# ---------------------------------------------------------------------------
# escalate_to_human
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escalate_to_human(executor):
    """escalate_to_human returns acknowledgment."""
    result = json.loads(await executor.execute("escalate_to_human", {
        "reason": "Customer complaint",
        "priority": 2,
        "summary": "Damaged product received",
    }))

    assert result["status"] == "escalation_requested"
    assert result["reason"] == "Customer complaint"
    assert result["priority"] == 2


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_tool(executor):
    """Unknown tool names return an error."""
    result = json.loads(await executor.execute("nonexistent_tool", {}))

    assert "error" in result
    assert "Unknown tool" in result["error"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_execution_error_handled(executor, product_matcher):
    """Exceptions during tool execution are caught and returned as errors."""
    product_matcher.find_products.side_effect = RuntimeError("DB connection lost")

    result = json.loads(await executor.execute("search_products", {"query": "saree"}))

    assert "error" in result
    assert result["error"] == "Tool execution failed."
