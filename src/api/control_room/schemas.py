from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ControlRoomMetricSet(BaseModel):
    messages_received: int
    messages_processed: int
    messages_failed: int
    auto_replies_sent: int
    handoffs_created: int
    avg_processing_ms: float | None
    open_conversations: int
    human_takeover_conversations: int


class ControlRoomHealth(BaseModel):
    database: str
    redis: str
    worker: str
    whatsapp: str
    claude: str
    speech: str


class ControlRoomSummary(BaseModel):
    status: str
    last_activity_at: datetime | None
    queue_depth: int
    processing_depth: int
    dead_letter_depth: int
    metrics: ControlRoomMetricSet
    health: ControlRoomHealth


class EventSummary(BaseModel):
    id: UUID
    created_at: datetime
    component: str
    event_type: str
    event_level: str
    event_status: str | None
    summary: str
    customer_phone_masked: str | None
    conversation_id: UUID | None
    message_id: UUID | None
    handoff_id: UUID | None
    details: dict | None


class ControlRoomCustomer(BaseModel):
    id: UUID
    name: str | None
    phone: str
    language: str | None
    dialect: str | None


class ConversationSummary(BaseModel):
    conversation_id: UUID
    customer_id: UUID
    customer_name: str | None
    customer_phone: str
    status: str
    message_count: int
    ai_response_count: int
    started_at: datetime
    last_message_at: datetime | None


class MessageSummary(BaseModel):
    id: UUID
    direction: str
    message_type: str
    content: str | None
    voice_transcription: str | None
    created_at: datetime


class ConversationRecord(BaseModel):
    conversation_id: UUID
    status: str
    started_at: datetime
    last_message_at: datetime | None
    message_count: int
    ai_response_count: int
    customer: ControlRoomCustomer
    messages: list[MessageSummary]


class HandoffRecord(BaseModel):
    id: UUID
    conversation_id: UUID
    customer_name: str | None
    customer_phone: str
    reason: str
    context_summary: str
    suggested_response: str | None
    priority: int
    status: str
    created_at: datetime
    resolved_at: datetime | None
    notes: str | None


class HandoffDetail(HandoffRecord):
    conversation: ConversationRecord


class OwnerNoteRequest(BaseModel):
    note: str | None = None
