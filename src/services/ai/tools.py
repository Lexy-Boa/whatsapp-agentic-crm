"""
Claude tool definitions for the agentic conversation pipeline.

These schemas follow the Anthropic tool_use API format. Claude decides
which tools to call based on the conversation context — no manual
intent-to-action mapping needed.
"""

from __future__ import annotations

TOOLS: list[dict] = [
    {
        "name": "search_products",
        "description": (
            "Search the product catalog for items matching the customer's request. "
            "Use this when the customer asks about products, wants recommendations, "
            "or describes what they're looking for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query describing what the customer wants.",
                },
                "occasion": {
                    "type": "string",
                    "description": "Occasion the product is for (e.g. wedding, casual, festival).",
                },
                "price_min": {
                    "type": "number",
                    "description": "Minimum price in INR.",
                },
                "price_max": {
                    "type": "number",
                    "description": "Maximum price in INR.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Default 3.",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "lookup_order",
        "description": (
            "Look up an order by order ID or customer phone number. "
            "Use this when the customer asks about their order status, delivery, or tracking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order ID to look up.",
                },
                "customer_phone": {
                    "type": "string",
                    "description": "Customer phone number (E.164 format without +).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "check_inventory",
        "description": (
            "Check if a specific product is in stock, optionally for a particular size or color. "
            "Use this when the customer asks about availability of a specific item."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku": {
                    "type": "string",
                    "description": "Product SKU code (e.g. DMB-2341).",
                },
                "size": {
                    "type": "string",
                    "description": "Size to check (e.g. S, M, L, XL, Free Size).",
                },
                "color": {
                    "type": "string",
                    "description": "Color variant to check.",
                },
            },
            "required": ["sku"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Escalate the conversation to a human agent. Use this for: "
            "complaints, refund/return requests, custom or bulk orders, "
            "when the customer explicitly asks for a human, "
            "or queries beyond product knowledge (account issues, delivery disputes)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason for escalation.",
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority 1-10 (1=urgent, 10=low). Complaints=2, order issues=4, general=6.",
                    "minimum": 1,
                    "maximum": 10,
                },
                "summary": {
                    "type": "string",
                    "description": "Summary of the conversation for the human agent.",
                },
            },
            "required": ["reason", "priority", "summary"],
        },
    },
]
