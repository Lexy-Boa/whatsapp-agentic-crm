"""
Natural language response generation for the fashion store assistant.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field

from src.services.ai.claude_client import ClaudeClient
from src.services.ai.prompts.system import build_system_prompt
from src.services.ai.store_config import DEFAULT_STORE_CONFIG

logger = structlog.get_logger(__name__)

_HANDOFF_INTENTS = frozenset({"complaint", "order_status"})


@dataclass
class ResponseContext:
    customer_name: str | None
    customer_language: str
    customer_dialect: str | None
    conversation_history: list[dict]
    current_message: str
    message_type: str
    intent: str
    entities: dict
    products: list[dict]
    store_config: dict


@dataclass
class GeneratedResponse:
    text: str
    language: str
    confidence: float
    should_handoff: bool
    handoff_reason: str | None
    products_mentioned: list[str]
    expects_reply: bool  # True if the response ends with "?"


def _format_products(products: list[dict]) -> str:
    """Format a product list as a brief reference block for Claude."""
    lines = ["Available products for this query:"]
    for i, p in enumerate(products, 1):
        name = p.get("name", "Unknown")
        code = p.get("code", "")
        price = p.get("price", "")
        stock = p.get("in_stock", True)
        stock_label = "in stock" if stock else "out of stock"
        parts = [f"{i}. {name}"]
        if code:
            parts[0] += f" ({code})"
        if price:
            parts.append(f"Price: ₹{price}")
        parts.append(f"Status: {stock_label}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


class ResponseGenerator:
    """
    Generates natural language responses for the fashion store assistant.

    Usage::

        generator = ResponseGenerator(claude_client=ClaudeClient())
        response = await generator.generate(context)
    """

    def __init__(self, claude_client: ClaudeClient) -> None:
        self._claude = claude_client

    async def generate(self, context: ResponseContext) -> GeneratedResponse:
        """
        Generate a response for the given context.

        Args:
            context: Full conversation and intent context.

        Returns:
            GeneratedResponse with the generated text and metadata.
        """
        system = build_system_prompt(
            store_config=context.store_config,
            language=context.customer_language,
            dialect=context.customer_dialect,
        )

        # Build messages list: last 10 history turns + current message
        messages: list[dict] = []
        if context.conversation_history:
            messages.extend(context.conversation_history[-10:])

        # Compose user turn content
        user_content = context.current_message
        if context.products:
            product_block = _format_products(context.products)
            user_content = f"{product_block}\n\nCustomer: {context.current_message}"

        messages.append({"role": "user", "content": user_content})

        max_tokens = context.store_config.get("response_settings", {}).get(
            "max_response_length", 500
        )

        text = await self._claude.complete(
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )

        should_handoff = context.intent in _HANDOFF_INTENTS
        handoff_reason: str | None = None
        if should_handoff:
            handoff_reason = f"Intent '{context.intent}' requires human agent"

        # Collect product codes/names mentioned in response
        products_mentioned: list[str] = []
        for p in context.products:
            code = p.get("code", "")
            name = p.get("name", "")
            if code and code in text:
                products_mentioned.append(code)
            elif name and name in text:
                products_mentioned.append(name)

        logger.info(
            "response_generated",
            language=context.customer_language,
            intent=context.intent,
            should_handoff=should_handoff,
            length=len(text),
        )

        return GeneratedResponse(
            text=text,
            language=context.customer_language,
            confidence=1.0,
            should_handoff=should_handoff,
            handoff_reason=handoff_reason,
            products_mentioned=products_mentioned,
            expects_reply=text.rstrip().endswith("?"),
        )
