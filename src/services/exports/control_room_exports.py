from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import datetime

from src.models.conversation import Message
from src.models.handoff import Handoff
from src.models.system_event import SystemEvent


def conversations_to_csv(rows: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "conversation_id",
            "customer_name",
            "customer_phone",
            "status",
            "message_count",
            "ai_response_count",
            "started_at",
            "last_message_at",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def conversations_to_markdown(rows: list[dict]) -> str:
    lines = ["# Conversations", ""]
    for row in rows:
        lines.extend(
            [
                f"## Conversation {row['conversation_id']}",
                f"- Customer: {row['customer_name'] or 'Unknown'}",
                f"- Phone: {row['customer_phone']}",
                f"- Status: {row['status']}",
                f"- Message count: {row['message_count']}",
                f"- AI replies: {row['ai_response_count']}",
                f"- Started: {row['started_at']}",
                f"- Last message: {row['last_message_at'] or 'n/a'}",
                "",
            ]
        )
    return "\n".join(lines)


def handoffs_to_csv(handoffs: Iterable[Handoff]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "handoff_id",
            "conversation_id",
            "reason",
            "status",
            "priority",
            "created_at",
            "resolved_at",
            "summary",
            "suggested_response",
            "owner_notes",
        ],
    )
    writer.writeheader()
    for handoff in handoffs:
        writer.writerow(
            {
                "handoff_id": str(handoff.id),
                "conversation_id": str(handoff.conversation_id),
                "reason": handoff.reason,
                "status": handoff.status.value,
                "priority": handoff.priority,
                "created_at": handoff.created_at.isoformat(),
                "resolved_at": handoff.resolved_at.isoformat() if handoff.resolved_at else "",
                "summary": handoff.context_summary,
                "suggested_response": handoff.suggested_response or "",
                "owner_notes": handoff.notes or "",
            }
        )
    return output.getvalue()


def activity_to_csv(events: Iterable[SystemEvent]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "event_id",
            "created_at",
            "component",
            "event_type",
            "event_level",
            "event_status",
            "summary",
            "customer_phone_masked",
            "conversation_id",
            "message_id",
            "handoff_id",
        ],
    )
    writer.writeheader()
    for event in events:
        writer.writerow(
            {
                "event_id": str(event.id),
                "created_at": event.created_at.isoformat(),
                "component": event.component,
                "event_type": event.event_type,
                "event_level": event.event_level,
                "event_status": event.event_status or "",
                "summary": event.summary,
                "customer_phone_masked": event.customer_phone_masked or "",
                "conversation_id": str(event.conversation_id) if event.conversation_id else "",
                "message_id": str(event.message_id) if event.message_id else "",
                "handoff_id": str(event.handoff_id) if event.handoff_id else "",
            }
        )
    return output.getvalue()


def conversation_detail_to_markdown(conversation: dict, messages: list[Message]) -> str:
    lines = [
        f"# Conversation {conversation['conversation_id']}",
        "",
        f"- Customer: {conversation['customer_name'] or 'Unknown'}",
        f"- Phone: {conversation['customer_phone']}",
        f"- Status: {conversation['status']}",
        f"- Started: {conversation['started_at']}",
        f"- Last message: {conversation['last_message_at'] or 'n/a'}",
        f"- Message count: {conversation['message_count']}",
        "",
        "## Messages",
        "",
    ]
    for msg in messages:
        lines.append(
            f"- {msg.created_at.isoformat()} | {msg.direction.value} | {msg.message_type.value} | {msg.content or '[media]'}"
        )
    return "\n".join(lines)


def handoffs_to_markdown(handoffs: Iterable[Handoff]) -> str:
    lines = ["# Handoffs", ""]
    for handoff in handoffs:
        lines.extend(
            [
                f"## Handoff {handoff.id}",
                f"- Conversation: {handoff.conversation_id}",
                f"- Reason: {handoff.reason}",
                f"- Status: {handoff.status.value}",
                f"- Priority: {handoff.priority}",
                f"- Created: {handoff.created_at.isoformat()}",
                f"- Resolved: {handoff.resolved_at.isoformat() if handoff.resolved_at else 'n/a'}",
                f"- Summary: {handoff.context_summary}",
                f"- Owner notes: {handoff.notes or 'n/a'}",
                "",
            ]
        )
    return "\n".join(lines)


def activity_to_markdown(events: Iterable[SystemEvent]) -> str:
    lines = ["# Activity Feed", ""]
    for event in events:
        lines.extend(
            [
                f"## {event.created_at.isoformat()} - {event.summary}",
                f"- Component: {event.component}",
                f"- Type: {event.event_type}",
                f"- Level: {event.event_level}",
                f"- Status: {event.event_status or 'n/a'}",
                f"- Customer: {event.customer_phone_masked or 'n/a'}",
                "",
            ]
        )
    return "\n".join(lines)
