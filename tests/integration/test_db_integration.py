"""
Integration tests that hit a real PostgreSQL database.

These tests verify that repository operations, ORM mappings, and SQL queries
work correctly end-to-end. Each test uses the `db_session` fixture which
creates tables, runs the test inside a transaction, and rolls back afterward.

Requires: `docker compose up -d postgres`
Skip:     Tests are automatically skipped if Postgres is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

from src.db.repositories.conversation_repo import ConversationRepository
from src.db.repositories.customer_repo import CustomerRepository
from src.db.repositories.message_repo import MessageRepository
from src.db.repositories.product_repo import ProductRepository
from src.models.conversation import ConversationStatus, MessageDirection

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# Customer tests
# ---------------------------------------------------------------------------

async def test_customer_get_or_create_new(db_session):
    """First call creates a new customer."""
    repo = CustomerRepository(db_session)
    customer, created = await repo.get_or_create("919876543210")

    assert created is True
    assert customer.phone_number == "919876543210"
    assert customer.id is not None


async def test_customer_get_or_create_idempotent(db_session):
    """Calling get_or_create twice with the same phone returns the same customer."""
    repo = CustomerRepository(db_session)
    customer1, created1 = await repo.get_or_create("919876543210")
    customer2, created2 = await repo.get_or_create("919876543210")

    assert created1 is True
    assert created2 is False
    assert customer1.id == customer2.id


async def test_customer_get_or_create_strips_plus(db_session):
    """Leading + is stripped from phone numbers."""
    repo = CustomerRepository(db_session)
    customer, _ = await repo.get_or_create("+919876543210")

    assert customer.phone_number == "919876543210"

    # Fetching without + should find the same customer
    found = await repo.get_by_phone("919876543210")
    assert found is not None
    assert found.id == customer.id


async def test_customer_update_language(db_session):
    """update_language sets detected_language and detected_dialect."""
    repo = CustomerRepository(db_session)
    customer, _ = await repo.get_or_create("919876543210")

    await repo.update_language(customer.id, "ml", "thrissur")
    await db_session.flush()

    # Re-fetch to verify persistence
    refreshed = await repo.get_by_phone("919876543210")
    assert refreshed.detected_language == "ml"
    assert refreshed.detected_dialect == "thrissur"


# ---------------------------------------------------------------------------
# Conversation tests
# ---------------------------------------------------------------------------

async def test_conversation_create_and_get_active(db_session):
    """Created conversation is returned by get_active."""
    customer_repo = CustomerRepository(db_session)
    conv_repo = ConversationRepository(db_session)

    customer, _ = await customer_repo.get_or_create("919876543210")
    conv = await conv_repo.create(customer.id)

    assert conv.status == ConversationStatus.bot
    assert conv.message_count == 0

    active = await conv_repo.get_active(customer.id)
    assert active is not None
    assert active.id == conv.id


async def test_conversation_update_status(db_session):
    """update_status changes the conversation status."""
    customer_repo = CustomerRepository(db_session)
    conv_repo = ConversationRepository(db_session)

    customer, _ = await customer_repo.get_or_create("919876543210")
    conv = await conv_repo.create(customer.id)

    await conv_repo.update_status(conv.id, ConversationStatus.human_takeover)
    await db_session.flush()

    fetched = await conv_repo.get_by_id(conv.id)
    assert fetched.status == ConversationStatus.human_takeover


async def test_conversation_increment_counters(db_session):
    """increment_message_count and increment_ai_response_count update correctly."""
    customer_repo = CustomerRepository(db_session)
    conv_repo = ConversationRepository(db_session)

    customer, _ = await customer_repo.get_or_create("919876543210")
    conv = await conv_repo.create(customer.id)

    await conv_repo.increment_message_count(conv.id)
    await conv_repo.increment_message_count(conv.id)
    await conv_repo.increment_ai_response_count(conv.id)
    await db_session.flush()

    fetched = await conv_repo.get_by_id(conv.id)
    assert fetched.message_count == 2
    assert fetched.ai_response_count == 1


async def test_conversation_closed_not_returned_by_get_active(db_session):
    """A closed conversation is not returned by get_active."""
    customer_repo = CustomerRepository(db_session)
    conv_repo = ConversationRepository(db_session)

    customer, _ = await customer_repo.get_or_create("919876543210")
    conv = await conv_repo.create(customer.id)
    await conv_repo.update_status(conv.id, ConversationStatus.closed)
    await db_session.flush()

    active = await conv_repo.get_active(customer.id)
    assert active is None


# ---------------------------------------------------------------------------
# Message tests
# ---------------------------------------------------------------------------

async def test_message_save_inbound_and_get_recent(db_session):
    """Saved inbound messages are returned by get_recent in chronological order."""
    customer_repo = CustomerRepository(db_session)
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)

    customer, _ = await customer_repo.get_or_create("919876543210")
    conv = await conv_repo.create(customer.id)

    msg1 = await msg_repo.save_inbound(
        conversation_id=conv.id,
        customer_id=customer.id,
        message_type="text",
        content="Hello",
    )
    msg2 = await msg_repo.save_inbound(
        conversation_id=conv.id,
        customer_id=customer.id,
        message_type="text",
        content="I need help",
    )

    recent = await msg_repo.get_recent(conv.id, limit=10)

    assert len(recent) == 2
    # Oldest first
    assert recent[0].content == "Hello"
    assert recent[1].content == "I need help"
    assert recent[0].direction == MessageDirection.inbound


async def test_message_save_outbound(db_session):
    """Outbound messages are saved with correct direction."""
    customer_repo = CustomerRepository(db_session)
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)

    customer, _ = await customer_repo.get_or_create("919876543210")
    conv = await conv_repo.create(customer.id)

    msg = await msg_repo.save_outbound(
        conversation_id=conv.id,
        customer_id=customer.id,
        message_type="text",
        content="How can I help?",
        whatsapp_message_id="wamid_out_001",
    )

    assert msg.direction == MessageDirection.outbound
    assert msg.content == "How can I help?"


async def test_message_get_recent_respects_limit(db_session):
    """get_recent returns at most `limit` messages."""
    customer_repo = CustomerRepository(db_session)
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)

    customer, _ = await customer_repo.get_or_create("919876543210")
    conv = await conv_repo.create(customer.id)

    for i in range(5):
        await msg_repo.save_inbound(
            conversation_id=conv.id,
            customer_id=customer.id,
            message_type="text",
            content=f"Message {i}",
        )

    recent = await msg_repo.get_recent(conv.id, limit=3)
    assert len(recent) == 3
    # Should be the 3 most recent, oldest first
    assert recent[0].content == "Message 2"
    assert recent[2].content == "Message 4"


# ---------------------------------------------------------------------------
# Product tests
# ---------------------------------------------------------------------------

async def test_product_upsert_create(db_session):
    """Upserting a new product creates it."""
    repo = ProductRepository(db_session)
    store_id = uuid.uuid4()

    product, created = await repo.upsert({
        "sku": "DMB-001",
        "name": "Red Silk Saree",
        "description": "Beautiful red silk saree",
        "category": "sarees",
        "base_price": 12000,
        "store_id": store_id,
        "shopify_id": "shop_001",
    })

    assert created is True
    assert product.sku == "DMB-001"
    assert product.name == "Red Silk Saree"
    assert float(product.base_price) == 12000.0


async def test_product_upsert_update(db_session):
    """Upserting an existing product (by shopify_id) updates it."""
    repo = ProductRepository(db_session)
    store_id = uuid.uuid4()

    product1, created1 = await repo.upsert({
        "sku": "DMB-001",
        "name": "Red Silk Saree",
        "category": "sarees",
        "base_price": 12000,
        "store_id": store_id,
        "shopify_id": "shop_001",
    })

    product2, created2 = await repo.upsert({
        "sku": "DMB-001",
        "name": "Red Silk Saree - Updated",
        "category": "sarees",
        "base_price": 11000,
        "store_id": store_id,
        "shopify_id": "shop_001",
    })

    assert created1 is True
    assert created2 is False
    assert product2.name == "Red Silk Saree - Updated"
    assert float(product2.base_price) == 11000.0


async def test_product_get_by_sku_scoped(db_session):
    """get_by_sku returns the product scoped by store_id."""
    repo = ProductRepository(db_session)
    store_a = uuid.uuid4()
    store_b = uuid.uuid4()

    await repo.upsert({
        "sku": "DMB-001",
        "name": "Saree A",
        "category": "sarees",
        "base_price": 10000,
        "store_id": store_a,
    })

    # Store A can find it
    found = await repo.get_by_sku(store_a, "DMB-001")
    assert found is not None
    assert found.name == "Saree A"

    # Store B cannot
    not_found = await repo.get_by_sku(store_b, "DMB-001")
    assert not_found is None


async def test_product_search_by_name(db_session):
    """search_by_name finds products by case-insensitive substring match."""
    repo = ProductRepository(db_session)
    store_id = uuid.uuid4()

    await repo.upsert({
        "sku": "DMB-001",
        "name": "Red Silk Saree",
        "category": "sarees",
        "base_price": 12000,
        "store_id": store_id,
    })
    await repo.upsert({
        "sku": "DMB-002",
        "name": "Blue Cotton Shirt",
        "category": "shirts",
        "base_price": 2000,
        "store_id": store_id,
    })

    results = await repo.search_by_name(store_id, "silk")
    assert len(results) == 1
    assert results[0].name == "Red Silk Saree"

    # Case insensitive
    results_upper = await repo.search_by_name(store_id, "SILK")
    assert len(results_upper) == 1
