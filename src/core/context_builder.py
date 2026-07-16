"""
Context builder — assemble handoff summaries from DB / domain data.

Simplified after tool-use migration: build_response_context() removed
(Claude handles this via the agentic loop). Only build_handoff_summary()
remains for the agent dashboard.
"""

from __future__ import annotations

import structlog

from src.db.repositories.message_repo import MessageRepository
from src.models.conversation import Conversation, Message, MessageDirection

logger = structlog.get_logger(__name__)


class ContextBuilder:
    """
    Build context objects for handoff summaries.

    Injected into services that need to generate summaries for human agents.
    """

    def __init__(self, message_repo: MessageRepository) -> None:
        self._message_repo = message_repo

    async def build_handoff_summary(
        self,
        conversation: Conversation,
        recent_messages: list[Message],
    ) -> str:
        """
        Build a plain-text summary for the human agent who will take over.

        Includes the last few message exchanges.
        """
        lines: list[str] = []

        if recent_messages:
            lines.append("Recent conversation:")
            for msg in recent_messages[-6:]:
                direction = "Customer" if msg.direction == MessageDirection.inbound else "Bot"
                content = (msg.content or "")[:120]
                if content:
                    lines.append(f"  {direction}: {content}")

        return "\n".join(lines) if lines else "No conversation history available."
