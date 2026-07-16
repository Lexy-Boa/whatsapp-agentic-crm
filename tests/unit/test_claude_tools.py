"""
Unit tests for the Claude agentic tool-use loop.

Mocks the Anthropic API to return tool_use blocks and verifies the
complete_with_tools() method handles all edge cases.
"""

from __future__ import annotations

import json
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.ai.claude_client import ClaudeClient, ToolCallLog, ToolCompletionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_block(text: str):
    return types.SimpleNamespace(type="text", text=text)


def _make_tool_use_block(tool_id: str, name: str, input_data: dict):
    return types.SimpleNamespace(type="tool_use", id=tool_id, name=name, input=input_data)


def _make_usage(input_tokens: int = 100, output_tokens: int = 50):
    return types.SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def _make_response(content_blocks, usage=None):
    return types.SimpleNamespace(
        content=content_blocks,
        usage=usage or _make_usage(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_text_only_response():
    """When Claude returns only text (no tools), loop completes in one round."""
    client = ClaudeClient.__new__(ClaudeClient)
    client._model = "claude-sonnet-4-6"
    client._max_tokens = 4096
    client._temperature = 0.7

    response = _make_response([_make_text_block("Hello! How can I help?")])
    client._create_with_tools = AsyncMock(return_value=response)

    tool_executor = AsyncMock()

    result = await client.complete_with_tools(
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Hi!"}],
        tools=[],
        tool_executor=tool_executor,
    )

    assert result.response_text == "Hello! How can I help?"
    assert len(result.tool_calls_log) == 0
    assert not result.escalated
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    tool_executor.execute.assert_not_called()


@pytest.mark.asyncio
async def test_single_tool_call():
    """Claude calls one tool, gets result, then responds with text."""
    client = ClaudeClient.__new__(ClaudeClient)
    client._model = "claude-sonnet-4-6"
    client._max_tokens = 4096
    client._temperature = 0.7

    # Round 1: Claude calls search_products
    round1_response = _make_response([
        _make_tool_use_block("call_1", "search_products", {"query": "red saree"}),
    ])
    # Round 2: Claude responds with text after seeing tool result
    round2_response = _make_response([
        _make_text_block("We have beautiful red sarees!"),
    ])

    client._create_with_tools = AsyncMock(side_effect=[round1_response, round2_response])

    tool_executor = AsyncMock()
    tool_executor.execute.return_value = json.dumps({
        "products": [{"name": "Red Silk Saree", "price": 12000}]
    })

    result = await client.complete_with_tools(
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Show me red sarees"}],
        tools=[{"name": "search_products"}],
        tool_executor=tool_executor,
    )

    assert result.response_text == "We have beautiful red sarees!"
    assert len(result.tool_calls_log) == 1
    assert result.tool_calls_log[0].tool_name == "search_products"
    assert not result.escalated
    tool_executor.execute.assert_called_once_with("search_products", {"query": "red saree"})


@pytest.mark.asyncio
async def test_escalation_via_tool():
    """escalate_to_human tool sets escalation flags on the result."""
    client = ClaudeClient.__new__(ClaudeClient)
    client._model = "claude-sonnet-4-6"
    client._max_tokens = 4096
    client._temperature = 0.7

    escalation_input = {
        "reason": "Customer complaint",
        "priority": 2,
        "summary": "Damaged product received",
    }

    # Round 1: Claude escalates
    round1_response = _make_response([
        _make_text_block("I'm sorry about that."),
        _make_tool_use_block("call_1", "escalate_to_human", escalation_input),
    ])
    # Round 2: Claude's final message after escalation
    round2_response = _make_response([
        _make_text_block("Let me connect you with our team."),
    ])

    client._create_with_tools = AsyncMock(side_effect=[round1_response, round2_response])

    tool_executor = AsyncMock()
    tool_executor.execute.return_value = json.dumps({"status": "escalation_requested"})

    result = await client.complete_with_tools(
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "I got a damaged product!"}],
        tools=[{"name": "escalate_to_human"}],
        tool_executor=tool_executor,
    )

    assert result.escalated
    assert result.escalation_reason == "Customer complaint"
    assert result.escalation_priority == 2
    assert result.escalation_summary == "Damaged product received"


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_round():
    """Claude calls multiple tools in a single response."""
    client = ClaudeClient.__new__(ClaudeClient)
    client._model = "claude-sonnet-4-6"
    client._max_tokens = 4096
    client._temperature = 0.7

    # Round 1: Two tool calls
    round1_response = _make_response([
        _make_tool_use_block("call_1", "search_products", {"query": "saree"}),
        _make_tool_use_block("call_2", "check_inventory", {"sku": "DMB-001"}),
    ])
    # Round 2: Final text
    round2_response = _make_response([
        _make_text_block("The saree is in stock!"),
    ])

    client._create_with_tools = AsyncMock(side_effect=[round1_response, round2_response])

    call_count = 0

    async def mock_execute(name, input_data):
        nonlocal call_count
        call_count += 1
        if name == "search_products":
            return json.dumps({"products": [{"name": "Saree", "sku": "DMB-001"}]})
        return json.dumps({"in_stock": True})

    tool_executor = AsyncMock()
    tool_executor.execute = mock_execute

    result = await client.complete_with_tools(
        system="test",
        messages=[{"role": "user", "content": "Is the saree in stock?"}],
        tools=[],
        tool_executor=tool_executor,
    )

    assert result.response_text == "The saree is in stock!"
    assert len(result.tool_calls_log) == 2
    assert call_count == 2


@pytest.mark.asyncio
async def test_max_tool_rounds_cap():
    """Loop stops at max_tool_rounds and returns a safe fallback."""
    client = ClaudeClient.__new__(ClaudeClient)
    client._model = "claude-sonnet-4-6"
    client._max_tokens = 4096
    client._temperature = 0.7

    # Every round returns a tool call — should be capped
    infinite_response = _make_response([
        _make_tool_use_block("call_n", "search_products", {"query": "loop"}),
    ])
    client._create_with_tools = AsyncMock(return_value=infinite_response)

    tool_executor = AsyncMock()
    tool_executor.execute.return_value = json.dumps({"products": []})

    result = await client.complete_with_tools(
        system="test",
        messages=[{"role": "user", "content": "test"}],
        tools=[],
        tool_executor=tool_executor,
        max_tool_rounds=3,
    )

    # Should have stopped after 3 rounds
    assert len(result.tool_calls_log) == 3
    assert result.escalated  # safety escalation
    assert "trouble processing" in result.response_text


@pytest.mark.asyncio
async def test_products_tracked_from_search():
    """Products from search_products results are tracked in products_referenced."""
    client = ClaudeClient.__new__(ClaudeClient)
    client._model = "claude-sonnet-4-6"
    client._max_tokens = 4096
    client._temperature = 0.7

    round1_response = _make_response([
        _make_tool_use_block("call_1", "search_products", {"query": "saree"}),
    ])
    round2_response = _make_response([
        _make_text_block("Here you go!"),
    ])

    client._create_with_tools = AsyncMock(side_effect=[round1_response, round2_response])

    search_result = json.dumps({
        "products": [
            {"name": "Red Saree", "sku": "DMB-001", "price": 12000},
            {"name": "Blue Saree", "sku": "DMB-002", "price": 8000},
        ]
    })
    tool_executor = AsyncMock()
    tool_executor.execute.return_value = search_result

    result = await client.complete_with_tools(
        system="test",
        messages=[{"role": "user", "content": "show sarees"}],
        tools=[],
        tool_executor=tool_executor,
    )

    assert len(result.products_referenced) == 2
    assert result.products_referenced[0]["name"] == "Red Saree"


@pytest.mark.asyncio
async def test_token_counting_across_rounds():
    """Input and output tokens accumulate across multiple rounds."""
    client = ClaudeClient.__new__(ClaudeClient)
    client._model = "claude-sonnet-4-6"
    client._max_tokens = 4096
    client._temperature = 0.7

    round1_response = _make_response(
        [_make_tool_use_block("call_1", "search_products", {"query": "test"})],
        usage=_make_usage(100, 30),
    )
    round2_response = _make_response(
        [_make_text_block("Done!")],
        usage=_make_usage(200, 20),
    )

    client._create_with_tools = AsyncMock(side_effect=[round1_response, round2_response])

    tool_executor = AsyncMock()
    tool_executor.execute.return_value = json.dumps({"products": []})

    result = await client.complete_with_tools(
        system="test",
        messages=[{"role": "user", "content": "test"}],
        tools=[],
        tool_executor=tool_executor,
    )

    assert result.input_tokens == 300  # 100 + 200
    assert result.output_tokens == 50  # 30 + 20
