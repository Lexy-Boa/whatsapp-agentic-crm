"""
Test the Claude tool-use AI pipeline with a single message.

Sends a message through Claude with tools (search_products, escalate_to_human, etc.)
and shows the response and any tool calls made.

Requires ANTHROPIC_API_KEY in environment / .env.

Examples:
    python -m scripts.test_ai_response --message "looking for red saree under 10k" --language en
    python -m scripts.test_ai_response --message "ഈ കസവ് സാരിയുടെ വില എത്രയാണ്?" --language ml --dialect thrissur
    python -m scripts.test_ai_response --message "I got a damaged product!" --language en
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Make sure the project root is on sys.path when run directly
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def run(message: str, language: str, dialect: str | None) -> None:
    from src.config import get_settings
    from src.services.ai.claude_client import ClaudeClient
    from src.services.ai.prompts.system import build_system_prompt
    from src.services.ai.response_generator import DEFAULT_STORE_CONFIG
    from src.services.ai.tools import TOOLS

    settings = get_settings()
    if not settings.anthropic_api_key:
        print(
            "\nError: ANTHROPIC_API_KEY is not set.\n"
            "Add it to your .env file or export it as an environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n{'─' * 60}")
    print("AI PIPELINE — Claude tool-use test")
    print(f"{'─' * 60}")
    print(f"Message  : {message}")
    print(f"Language : {language}")
    if dialect:
        print(f"Dialect  : {dialect}")
    print(f"Model    : {settings.claude_model}")

    claude_client = ClaudeClient()

    # Mock tool executor that returns stub results (no DB needed)
    class StubToolExecutor:
        async def execute(self, tool_name: str, tool_input: dict) -> str:
            print(f"\n  [Tool called: {tool_name}]")
            print(f"  [Input: {json.dumps(tool_input, indent=2)}]")

            if tool_name == "search_products":
                return json.dumps({
                    "products": [
                        {"name": "Sample Kasavu Saree", "sku": "DMB-001", "price": 8500,
                         "in_stock": True, "match_score": 0.92},
                        {"name": "Red Silk Saree", "sku": "DMB-002", "price": 12000,
                         "in_stock": True, "match_score": 0.85},
                    ]
                })
            elif tool_name == "check_inventory":
                return json.dumps({
                    "product": "Sample Product", "sku": tool_input.get("sku", ""),
                    "in_stock": True, "variants": [{"size": "Free Size", "stock_quantity": 5}],
                })
            elif tool_name == "lookup_order":
                return json.dumps({
                    "message": "Order lookup not available in test mode.",
                })
            elif tool_name == "escalate_to_human":
                return json.dumps({
                    "status": "escalation_requested",
                    "reason": tool_input.get("reason", ""),
                    "priority": tool_input.get("priority", 5),
                })
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    try:
        system_prompt = build_system_prompt(
            store_config=DEFAULT_STORE_CONFIG,
            language=language,
            dialect=dialect,
        )

        print("\nSending to Claude with tools…")
        result = await claude_client.complete_with_tools(
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
            tools=TOOLS,
            tool_executor=StubToolExecutor(),
        )

        print(f"\n── Result {'─' * 50}")
        print(f"  Escalated      : {result.escalated}")
        if result.escalation_reason:
            print(f"  Reason         : {result.escalation_reason}")
            print(f"  Priority       : {result.escalation_priority}")
        print(f"  Tool calls     : {len(result.tool_calls_log)}")
        for i, call in enumerate(result.tool_calls_log, 1):
            print(f"    {i}. {call.tool_name}({json.dumps(call.tool_input)})")
        if result.products_referenced:
            print(f"  Products found : {len(result.products_referenced)}")
        print(f"  Input tokens   : {result.input_tokens}")
        print(f"  Output tokens  : {result.output_tokens}")
        print(f"\n  Response text:")
        print(f"  {result.response_text}")
        print()

    finally:
        await claude_client.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Test the Claude tool-use AI pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--message",
        required=True,
        metavar="TEXT",
        help="Customer message to process.",
    )
    p.add_argument(
        "--language",
        required=True,
        metavar="LANG",
        help="ISO 639-1 language code (e.g. ml, ta, en).",
    )
    p.add_argument(
        "--dialect",
        default=None,
        metavar="DIALECT",
        help="Optional dialect name (e.g. thrissur, madurai).",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args.message, args.language, args.dialect))


if __name__ == "__main__":
    main()
