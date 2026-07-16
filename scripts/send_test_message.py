"""
Send a test WhatsApp message to verify the API is working.

Usage:
    python -m scripts.send_test_message \\
        --to "+919876543210" \\
        --text "Hello! This is a test message from DemoBoutique."

Requires `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` to be set in `.env`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def run(to: str, text: str) -> None:
    from src.config import get_settings
    from src.services.whatsapp.client import WhatsAppClient

    settings = get_settings()

    if not settings.whatsapp_access_token:
        print("Error: WHATSAPP_ACCESS_TOKEN is not set in .env", file=sys.stderr)
        print("See docs/WHATSAPP_SETUP.md for setup instructions.", file=sys.stderr)
        sys.exit(1)

    if not settings.whatsapp_phone_number_id:
        print("Error: WHATSAPP_PHONE_NUMBER_ID is not set in .env", file=sys.stderr)
        print("See docs/WHATSAPP_SETUP.md for setup instructions.", file=sys.stderr)
        sys.exit(1)

    # Normalise phone number (strip leading +)
    to_normalised = to.lstrip("+")

    print(f"\n{'─' * 50}")
    print("  WhatsApp Test Message")
    print(f"{'─' * 50}")
    print(f"  To   : +{to_normalised}")
    print(f"  Text : {text[:60]}{'...' if len(text) > 60 else ''}")
    print()

    client = WhatsAppClient(access_token=settings.whatsapp_access_token, phone_number_id=settings.whatsapp_phone_number_id)
    try:
        result = await client.send_text(to_normalised, text)
        if result.success:
            print(f"  \033[92m✓\033[0m  Message sent successfully")
            if result.message_id:
                print(f"       Message ID: {result.message_id}")
        else:
            print(f"  \033[91m✗\033[0m  Send failed: {result.error}", file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"  \033[91m✗\033[0m  Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.close()

    print()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Send a test WhatsApp message.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--to",
        required=True,
        help="Recipient phone number in E.164 format (e.g. +919876543210)",
    )
    p.add_argument(
        "--text",
        required=True,
        help="Message text to send",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(to=args.to, text=args.text))


if __name__ == "__main__":
    main()
