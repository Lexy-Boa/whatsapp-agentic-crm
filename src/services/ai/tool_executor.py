"""
Tool execution layer for Claude's tool_use calls.

Routes tool calls to existing services (ProductMatcher, ProductRepository)
and returns results as JSON strings for Claude's next turn.
"""

from __future__ import annotations

import json
import uuid

import structlog

from src.core.privacy import redact_operational_text
from src.core.product_matcher import MatchQuery, ProductMatcher
from src.db.repositories.product_repo import ProductRepository

logger = structlog.get_logger(__name__)


class ToolExecutor:
    """
    Execute tool calls from Claude and return results as JSON strings.

    Maintains existing DI pattern — all dependencies injected via constructor.
    """

    def __init__(
        self,
        product_matcher: ProductMatcher,
        product_repo: ProductRepository,
        store_id: uuid.UUID,
    ) -> None:
        self._product_matcher = product_matcher
        self._product_repo = product_repo
        self._store_id = store_id

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        """
        Execute a tool call and return the result as a JSON string.

        Errors are returned as JSON error messages (never raised) so Claude
        can decide how to handle them.
        """
        try:
            if tool_name == "search_products":
                return await self._search_products(tool_input)
            elif tool_name == "lookup_order":
                return await self._lookup_order(tool_input)
            elif tool_name == "check_inventory":
                return await self._check_inventory(tool_input)
            elif tool_name == "escalate_to_human":
                return await self._escalate_to_human(tool_input)
            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as exc:
            logger.warning(
                "tool_execution_error",
                tool=tool_name,
                error=redact_operational_text(exc),
            )
            return json.dumps({"error": "Tool execution failed."})

    async def _search_products(self, params: dict) -> str:
        query_text = params.get("query", "")
        occasion = params.get("occasion")
        price_min = params.get("price_min")
        price_max = params.get("price_max")
        limit = params.get("limit", 3)

        price_range = None
        if price_min is not None or price_max is not None:
            price_range = (
                float(price_min or 0),
                float(price_max or 999999),
            )

        query = MatchQuery(
            text=query_text,
            occasion=occasion,
            price_range=price_range,
        )

        matches = await self._product_matcher.find_products(
            query, self._store_id, limit=limit
        )

        if not matches:
            return json.dumps({"products": [], "message": "No products found matching your query."})

        products = []
        for m in matches:
            p = m.product
            variants = getattr(p, "variants", None) or []
            in_stock = any(getattr(v, "stock_quantity", 0) > 0 for v in variants) if variants else True
            products.append({
                "name": getattr(p, "name", ""),
                "sku": getattr(p, "sku", ""),
                "price": float(getattr(p, "base_price", 0)),
                "description": getattr(p, "description", "") or "",
                "category": getattr(p, "category", "") or "",
                "occasions": getattr(p, "occasions", []) or [],
                "in_stock": in_stock,
                "match_score": round(m.score, 3),
            })

        logger.info("tool_search_products", query_length=len(query_text), results=len(products))
        return json.dumps({"products": products})

    async def _lookup_order(self, params: dict) -> str:
        # Order lookup is a new capability — stub for now since we don't have
        # an order repository wired up yet
        order_id = params.get("order_id")
        customer_phone = params.get("customer_phone")

        if not order_id and not customer_phone:
            return json.dumps({"error": "Provide either order_id or customer_phone."})

        # TODO: Wire up order repository when available
        return json.dumps({
            "message": "Order lookup is not yet available. Please escalate to a human agent for order inquiries.",
            "order_id_provided": bool(order_id),
            "customer_phone_provided": bool(customer_phone),
        })

    async def _check_inventory(self, params: dict) -> str:
        sku = params.get("sku", "")
        size = params.get("size")
        color = params.get("color")

        product = await self._product_repo.get_by_sku(self._store_id, sku)
        if not product:
            return json.dumps({"error": f"Product with SKU '{sku}' not found."})

        variants = getattr(product, "variants", None) or []
        if not variants:
            return json.dumps({
                "product": getattr(product, "name", ""),
                "sku": sku,
                "in_stock": True,
                "message": "No variant data available; assumed in stock.",
            })

        # Filter variants by size/color if specified
        matching = variants
        if size:
            matching = [v for v in matching if getattr(v, "size", "").lower() == size.lower()]
        if color:
            matching = [v for v in matching if getattr(v, "color", "").lower() == color.lower()]

        if not matching:
            return json.dumps({
                "product": getattr(product, "name", ""),
                "sku": sku,
                "in_stock": False,
                "message": f"No variants found matching size={size}, color={color}.",
            })

        available = [
            {
                "size": getattr(v, "size", ""),
                "color": getattr(v, "color", ""),
                "stock_quantity": getattr(v, "stock_quantity", 0),
            }
            for v in matching
        ]

        in_stock = any(v["stock_quantity"] > 0 for v in available)
        return json.dumps({
            "product": getattr(product, "name", ""),
            "sku": sku,
            "in_stock": in_stock,
            "variants": available,
        })

    async def _escalate_to_human(self, params: dict) -> str:
        # The actual handoff creation is handled by the orchestrator after
        # seeing this tool call in the result. We just acknowledge it here.
        return json.dumps({
            "status": "escalation_requested",
            "reason": params.get("reason", ""),
            "priority": params.get("priority", 5),
            "summary": params.get("summary", ""),
        })
