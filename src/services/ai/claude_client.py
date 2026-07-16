"""
Async Claude API client with tool_use agentic loop.

Wraps the Anthropic AsyncAnthropic client with structured logging,
JSON-parsing helpers, and an agentic tool-use loop. Instantiate once
and reuse across requests.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import structlog
from anthropic import APIConnectionError, AsyncAnthropic, InternalServerError, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, before_sleep_log

from src.config import get_settings

logger = structlog.get_logger(__name__)
_std_logger = __import__("logging").getLogger(__name__)

# Matches ```json ... ``` or ``` ... ``` fences
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

_RETRYABLE_ERRORS = (APIConnectionError, RateLimitError, InternalServerError)


def _parse_json_response(text: str) -> dict:
    """Strip markdown fences then parse as JSON."""
    m = _FENCE_RE.search(text)
    raw = m.group(1) if m else text.strip()
    return json.loads(raw)


@dataclass
class ToolCallLog:
    """Record of a single tool call made during an agentic loop."""
    tool_name: str
    tool_input: dict
    result: str


@dataclass
class ToolCompletionResult:
    """Result of a complete_with_tools() call."""
    response_text: str
    tool_calls_log: list[ToolCallLog] = field(default_factory=list)
    escalated: bool = False
    escalation_reason: str | None = None
    escalation_priority: int = 5
    escalation_summary: str | None = None
    products_referenced: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class ClaudeClient:
    """
    Lightweight async wrapper around Anthropic's messages API.

    Create once at app startup and reuse — the underlying httpx client
    maintains a connection pool.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_model
        self._max_tokens = settings.claude_max_tokens
        self._temperature = settings.claude_temperature

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        wait=wait_exponential(min=1, max=30),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(_std_logger, __import__("logging").WARNING),
    )
    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """
        Send a chat completion request and return the assistant's text.

        Args:
            system:      System prompt.
            messages:    List of {"role": "user"|"assistant", "content": str}.
            max_tokens:  Override default max tokens.
            temperature: Override default temperature.

        Returns:
            The assistant's reply as a plain string.
        """
        response = await self._client.messages.create(
            model=self._model,
            system=system,
            messages=messages,
            max_tokens=max_tokens if max_tokens is not None else self._max_tokens,
            temperature=temperature if temperature is not None else self._temperature,
        )
        text = response.content[0].text
        logger.debug(
            "claude_complete",
            model=self._model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return text

    async def complete_json(
        self,
        system: str,
        user_prompt: str,
        max_tokens: int | None = None,
    ) -> dict:
        """
        Request a JSON response from Claude at temperature=0.

        Strips markdown code fences before parsing. Raises ValueError if
        the response cannot be parsed as JSON.

        Args:
            system:      System prompt instructing Claude to return JSON.
            user_prompt: The user-turn content.
            max_tokens:  Override default max tokens.

        Returns:
            Parsed JSON as a dict.
        """
        text = await self.complete(
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=max_tokens,
            temperature=0.0,
        )
        try:
            return _parse_json_response(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "claude_json_parse_error",
                response_length=len(text),
                error=str(exc),
            )
            raise ValueError(f"Claude returned non-JSON response: {exc}") from exc

    async def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor,
        max_tokens: int | None = None,
        temperature: float | None = None,
        max_tool_rounds: int = 5,
    ) -> ToolCompletionResult:
        """
        Agentic loop: send messages to Claude with tools, execute any tool
        calls, feed results back, repeat until Claude responds with text.

        Args:
            system:          System prompt.
            messages:        Conversation history.
            tools:           Tool schemas (Anthropic tool_use format).
            tool_executor:   Object with async execute(tool_name, tool_input) -> str.
            max_tokens:      Override default max tokens.
            temperature:     Override default temperature.
            max_tool_rounds: Safety cap on tool call rounds to prevent infinite loops.

        Returns:
            ToolCompletionResult with response text, tool call log, and metadata.
        """
        result = ToolCompletionResult(response_text="")
        current_messages = list(messages)

        for round_num in range(max_tool_rounds):
            response = await self._create_with_tools(
                system=system,
                messages=current_messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            result.input_tokens += response.usage.input_tokens
            result.output_tokens += response.usage.output_tokens

            # Collect text blocks and tool_use blocks from response
            text_parts: list[str] = []
            tool_uses: list[dict] = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            # If no tool calls, we're done — Claude's text is the response
            if not tool_uses:
                result.response_text = "\n".join(text_parts)
                break

            # Execute each tool call
            tool_results: list[dict] = []
            for tool_use in tool_uses:
                tool_result = await tool_executor.execute(
                    tool_use["name"], tool_use["input"]
                )

                log_entry = ToolCallLog(
                    tool_name=tool_use["name"],
                    tool_input=tool_use["input"],
                    result=tool_result,
                )
                result.tool_calls_log.append(log_entry)

                # Check for escalation
                if tool_use["name"] == "escalate_to_human":
                    result.escalated = True
                    result.escalation_reason = tool_use["input"].get("reason")
                    result.escalation_priority = tool_use["input"].get("priority", 5)
                    result.escalation_summary = tool_use["input"].get("summary")

                # Track products from search results
                if tool_use["name"] == "search_products":
                    try:
                        parsed = json.loads(tool_result)
                        result.products_referenced.extend(parsed.get("products", []))
                    except (json.JSONDecodeError, TypeError):
                        pass

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use["id"],
                    "content": tool_result,
                })

            # Build assistant message with the full response content
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            current_messages.append({"role": "assistant", "content": assistant_content})
            current_messages.append({"role": "user", "content": tool_results})

            logger.debug(
                "claude_tool_round",
                round=round_num + 1,
                tools_called=[t["name"] for t in tool_uses],
                escalated=result.escalated,
            )

            # If escalated, capture any text Claude already provided and stop
            if result.escalated:
                result.response_text = "\n".join(text_parts) if text_parts else ""
                # Do one more round to get Claude's final text after tool results
                continue
        else:
            # Exhausted max_tool_rounds — use whatever text we have
            logger.warning(
                "claude_max_tool_rounds_reached",
                max_rounds=max_tool_rounds,
                tool_calls=len(result.tool_calls_log),
            )
            if not result.response_text:
                result.response_text = "I'm having trouble processing your request. Let me connect you with our team."
                result.escalated = True
                result.escalation_reason = "max_tool_rounds_exceeded"
                result.escalation_priority = 4

        logger.info(
            "claude_tool_completion",
            model=self._model,
            tool_rounds=len(result.tool_calls_log),
            escalated=result.escalated,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return result

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        wait=wait_exponential(min=1, max=30),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(_std_logger, __import__("logging").WARNING),
    )
    async def _create_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ):
        """Single API call with tools. Separated for retry decorator."""
        return await self._client.messages.create(
            model=self._model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens if max_tokens is not None else self._max_tokens,
            temperature=temperature if temperature is not None else self._temperature,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
