"""
models package — imports all ORM models so that:
1. Alembic can find them via Base.metadata
2. SQLAlchemy resolves all forward-reference string annotations
3. Application code can import from one place: from src.models import Customer, Order, ...
"""

from src.models.base import Base, TimestampMixin, UUIDMixin
from src.models.customer import Customer, CustomerTag, CustomerTagAssignment
from src.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageStatus,
    MessageType,
    VoiceTranscription,
)
from src.models.product import Product, ProductVariant
from src.models.order import Order, OrderItem, OrderStatus, PaymentStatus
from src.models.handoff import Handoff, HandoffStatus
from src.models.system_event import SystemEvent

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDMixin",
    "Customer",
    "CustomerTag",
    "CustomerTagAssignment",
    "Conversation",
    "ConversationStatus",
    "Message",
    "MessageDirection",
    "MessageStatus",
    "MessageType",
    "VoiceTranscription",
    "Product",
    "ProductVariant",
    "Order",
    "OrderItem",
    "OrderStatus",
    "PaymentStatus",
    "Handoff",
    "HandoffStatus",
    "SystemEvent",
]
