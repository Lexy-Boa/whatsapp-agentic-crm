"""
Simulate the full handoff lifecycle using repository clients directly.

Usage:
    python -m scripts.simulate_handoff --store-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from src.db.postgres import close_db, get_session, init_db
from src.db.redis_client import close_redis, init_redis
from src.db.repositories.conversation_repo import ConversationRepository
from src.db.repositories.customer_repo import CustomerRepository
from src.db.repositories.handoff_repo import HandoffRepository
from src.models.conversation import ConversationStatus
from src.models.handoff import HandoffStatus


async def run(store_id: uuid.UUID) -> None:
    print(f"\n{'='*60}")
    print("WhatsApp Fashion CRM — Handoff Simulation")
    print(f"Store ID: {store_id}")
    print(f"{'='*60}\n")

    # ── Init DB & Redis ───────────────────────────────────────────────────
    await init_db()
    await init_redis()
    print("[ok] Database and Redis initialised")

    try:
        # Use a single session for the whole simulation
        async for session in get_session():
            customer_repo = CustomerRepository(session)
            conv_repo = ConversationRepository(session)
            handoff_repo = HandoffRepository(session)

            # ── Step 1: Get or create test customer ───────────────────────
            customer, created = await customer_repo.get_or_create("+919876500001")
            tag = "created" if created else "existing"
            print(f"[ok] Customer {tag}: {customer.id} ({customer.phone_number})")

            # ── Step 2: Get or create conversation ────────────────────────
            conv = await conv_repo.get_active(customer.id)
            if not conv:
                conv = await conv_repo.create(customer.id)
                print(f"[ok] Conversation created: {conv.id}")
            else:
                print(f"[ok] Conversation found:   {conv.id} (status={conv.status.value})")

            # ── Step 3: Create handoff ────────────────────────────────────
            handoff = await handoff_repo.create(
                conversation_id=conv.id,
                store_id=store_id,
                reason="complaint",
                context_summary="Customer reported a damaged product and requested a refund.",
                suggested_response="I'm sorry to hear about the damaged product. Let me connect you with our team.",
                priority=2,
            )
            print(f"[ok] Handoff created:      {handoff.id} (status=pending, priority={handoff.priority})")

            # ── Step 4: Assign handoff ────────────────────────────────────
            assigned = await handoff_repo.assign(handoff.id, agent_id="agent-001")
            print(f"[ok] Handoff assigned:     {'success' if assigned else 'FAILED'} → agent-001")

            # ── Step 5: Mark conversation as human_takeover ───────────────
            await conv_repo.update_status(conv.id, ConversationStatus.human_takeover)
            print(f"[ok] Conversation status → human_takeover")

            # ── Step 6: Resolve handoff ───────────────────────────────────
            resolved = await handoff_repo.resolve(
                handoff.id, notes="Refund processed and customer notified."
            )
            print(f"[ok] Handoff resolved:     {'success' if resolved else 'FAILED'}")

            # ── Step 7: Release conversation back to bot ──────────────────
            await conv_repo.update_status(conv.id, ConversationStatus.bot)
            print(f"[ok] Conversation status → bot (released back to AI)")

            # Commit happens automatically on session exit
            break

    finally:
        await close_db()
        await close_redis()
        print("\n[ok] Database and Redis connections closed")

    print(f"\n{'='*60}")
    print("Simulation complete!")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate the handoff lifecycle")
    parser.add_argument(
        "--store-id",
        required=True,
        type=uuid.UUID,
        help="UUID of the store to simulate against",
    )
    args = parser.parse_args()
    asyncio.run(run(args.store_id))


if __name__ == "__main__":
    main()
