from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class CustomerInfo(BaseModel):
    id: UUID
    phone: str
    name: str | None
    language: str | None
    dialect: str | None


class MessageInfo(BaseModel):
    id: UUID
    direction: str          # "inbound" / "outbound"
    message_type: str       # "text" / "audio" / ...
    content: str | None
    voice_transcription: str | None
    created_at: datetime


class HandoffSummary(BaseModel):
    id: UUID
    customer_name: str | None
    customer_phone: str
    reason: str
    priority: int
    context_summary: str    # first 200 chars
    created_at: datetime
    minutes_waiting: int


class HandoffDetail(BaseModel):
    id: UUID
    conversation_id: UUID
    customer: CustomerInfo
    reason: str
    context_summary: str
    suggested_response: str | None
    priority: int
    status: str
    created_at: datetime
    messages: list[MessageInfo]


class ConversationDetail(BaseModel):
    id: UUID
    customer: CustomerInfo
    status: str
    started_at: datetime
    message_count: int
    messages: list[MessageInfo]
