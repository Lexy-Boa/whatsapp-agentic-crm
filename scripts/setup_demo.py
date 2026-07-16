"""
Prepare the DemoBoutique demo environment.

Usage:
    python -m scripts.setup_demo --store-id <uuid>

What it does:
  1. reports AI and WhatsApp environment readiness
  2. syncs the DemoBoutique mock catalog into Postgres, with embeddings if available
  3. prints the recommended demo flows and acceptance checklist
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def run(store_id: uuid.UUID) -> None:
    from scripts.sync_products import run_mock_sync
    from src.config import get_settings

    settings = get_settings()
    missing: list[str] = []

    if not settings.groq_api_key.get_secret_value():
        missing.append("GROQ_API_KEY")
    if not settings.anthropic_api_key:
        missing.append("ANTHROPIC_API_KEY")
    if not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if not settings.whatsapp_access_token:
        missing.append("WHATSAPP_ACCESS_TOKEN")
    if not settings.whatsapp_phone_number_id:
        missing.append("WHATSAPP_PHONE_NUMBER_ID")
    if not settings.whatsapp_verify_token:
        missing.append("WHATSAPP_VERIFY_TOKEN")

    print("\n" + ("=" * 60))
    print("DemoBoutique Demo Setup")
    print("=" * 60)
    print(f"Store ID: {store_id}")

    if missing:
        print("\nMissing or unavailable settings:")
        for key in missing:
            print(f"  - {key}")
        print("\nContinuing in degraded setup mode so DB catalog prep can still finish.")
        print("Smart replies, voice, semantic search, or live WhatsApp may be unavailable until these are fixed.")

    await run_mock_sync(store_id)

    print("Recommended demo flows:")
    print("  1. Malayalam voice note -> same-language reply")
    print("  2. Tamil product request with budget -> recommendations")
    print("  3. SKU/stock question -> inventory-aware answer")
    print("  4. Complaint/refund request -> human handoff")
    print("\nAcceptance checklist:")
    print("  - inbound webhook reaches the app")
    print("  - worker processes the message end-to-end")
    print("  - voice transcription works")
    print("  - reply is in the expected language")
    print("  - handoff path is understandable")
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the DemoBoutique demo environment.")
    parser.add_argument("--store-id", required=True, help="Store UUID for the demo catalog.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        store_id = uuid.UUID(args.store_id)
    except ValueError:
        parser.error(f"Invalid UUID: {args.store_id}")
    asyncio.run(run(store_id))


if __name__ == "__main__":
    main()
