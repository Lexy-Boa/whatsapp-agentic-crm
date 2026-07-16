"""
Conversation orchestrator — the full end-to-end message processing pipeline.

Flow (7 steps, tool-use pipeline):
  1. Get / create Customer + Conversation
  2. Save inbound message
  3. Short-circuit if human agent is in control
  4. Process content  (transcribe voice; extract text from image caption)
  5. Single Claude call with tools (replaces intent→search→response→decision)
  6. Execute: send WhatsApp message OR create handoff record
  7. Persist + update counters
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

import structlog

from src.core.privacy import mask_phone, summarize_exception_for_operations
from src.core.product_matcher import ProductMatcher
from src.db.repositories.conversation_repo import ConversationRepository
from src.db.repositories.customer_repo import CustomerRepository
from src.db.repositories.handoff_repo import HandoffRepository
from src.db.repositories.message_repo import MessageRepository
from src.models.conversation import ConversationStatus, Message, MessageDirection
from src.services.ai.claude_client import ClaudeClient, ToolCompletionResult
from src.services.ai.prompts.system import build_system_prompt
from src.services.ai.tool_executor import ToolExecutor
from src.services.ai.tools import TOOLS
from src.services.observability.events import emit_system_event
from src.services.speech.transcriber import VoiceTranscriber
from src.services.whatsapp.client import WhatsAppClient
from src.services.whatsapp.policy import WhatsAppPolicy

if TYPE_CHECKING:
    from src.services.speech.tts import TextToSpeech

logger = structlog.get_logger(__name__)


@dataclass
class ProcessingResult:
    success: bool
    response_sent: bool
    response_text: str | None
    response_type: Literal["text", "voice", "none"]
    handoff_created: bool
    handoff_id: uuid.UUID | None
    error: str | None
    # Timing metrics
    total_time_ms: int
    transcription_time_ms: int | None
    ai_time_ms: int | None


class ConversationOrchestrator:
    """
    Wire all pipeline components together into a single process_message() call.

    Uses Claude's tool_use API for a single agentic call that handles
    intent detection, product search, and escalation decisions.
    """

    def __init__(
        self,
        store_id: uuid.UUID,
        store_config: dict,
        whatsapp_client: WhatsAppClient,
        transcriber: VoiceTranscriber,
        claude_client: ClaudeClient,
        tool_executor: ToolExecutor,
        tts: "TextToSpeech | None",
        customer_repo: CustomerRepository,
        conversation_repo: ConversationRepository,
        message_repo: MessageRepository,
        handoff_repo: HandoffRepository,
        outbound_policy: WhatsAppPolicy | None = None,
    ) -> None:
        self._store_id = store_id
        self._store_config = store_config
        self._whatsapp = whatsapp_client
        self._transcriber = transcriber
        self._claude = claude_client
        self._tool_executor = tool_executor
        self._tts = tts
        self._customer_repo = customer_repo
        self._conversation_repo = conversation_repo
        self._message_repo = message_repo
        self._handoff_repo = handoff_repo
        self._outbound_policy = outbound_policy or WhatsAppPolicy()

    async def process_message(
        self,
        customer_phone: str,
        message_type: Literal["text", "voice", "image"],
        content: str | None = None,
        media_bytes: bytes | None = None,
        media_mime_type: str | None = None,
        whatsapp_message_id: str | None = None,
    ) -> ProcessingResult:
        """
        Process one inbound WhatsApp message end-to-end.

        Returns a ProcessingResult regardless of success/failure — errors are
        caught and surfaced in the result rather than raised.
        """
        wall_start = time.monotonic()
        transcription_time_ms: int | None = None
        ai_time_ms: int | None = None
        customer = None
        conversation = None

        try:
            # -- Step 1: Customer + Conversation ---------------------------------
            customer, _ = await self._customer_repo.get_or_create(customer_phone)

            conversation = await self._conversation_repo.get_active(customer.id)
            if not conversation:
                conversation = await self._conversation_repo.create(customer.id)

            # -- Step 2: Save inbound message ------------------------------------
            inbound_msg = await self._message_repo.save_inbound(
                conversation_id=conversation.id,
                customer_id=customer.id,
                message_type=message_type,
                content=content,
                whatsapp_message_id=whatsapp_message_id,
            )
            await self._conversation_repo.increment_message_count(conversation.id)

            # -- Step 3: Short-circuit if human agent is in control ---------------
            if conversation.status == ConversationStatus.human_takeover:
                await self._customer_repo.update_last_seen(customer.id)
                logger.info(
                    "human_takeover_message_saved",
                    customer_phone=mask_phone(customer_phone),
                    conversation_id=str(conversation.id),
                )
                await emit_system_event(
                    event_type="message_parked_for_human",
                    event_level="info",
                    component="orchestrator",
                    summary="Inbound message saved while conversation is in human takeover.",
                    event_status="parked",
                    conversation_id=conversation.id,
                    message_id=inbound_msg.id,
                    customer_phone_masked=mask_phone(customer_phone),
                )
                return ProcessingResult(
                    success=True,
                    response_sent=False,
                    response_text=None,
                    response_type="none",
                    handoff_created=False,
                    handoff_id=None,
                    error=None,
                    total_time_ms=int((time.monotonic() - wall_start) * 1000),
                    transcription_time_ms=None,
                    ai_time_ms=None,
                )

            # -- Step 4: Process content -----------------------------------------
            text_to_process: str | None = content
            language: str = (
                getattr(customer, "detected_language", None)
                or customer.language_preference
                or "ml"
            )
            dialect: str | None = getattr(customer, "detected_dialect", None)

            if message_type == "voice" and media_bytes:
                await emit_system_event(
                    event_type="transcription_started",
                    event_level="info",
                    component="speech",
                    summary="Voice transcription started.",
                    event_status="processing",
                    conversation_id=conversation.id,
                    message_id=inbound_msg.id,
                    customer_phone_masked=mask_phone(customer_phone),
                )
                t_start = time.monotonic()
                try:
                    transcription = await self._transcriber.transcribe(
                        audio_bytes=media_bytes,
                        mime_type=media_mime_type or "audio/ogg",
                        language_hint=language,
                    )
                except Exception as exc:
                    transcription_time_ms = int((time.monotonic() - t_start) * 1000)
                    safe_error = summarize_exception_for_operations(exc)
                    await emit_system_event(
                        event_type="transcription_failed",
                        event_level="error",
                        component="speech",
                        summary="Voice transcription failed.",
                        event_status="failed",
                        conversation_id=conversation.id,
                        message_id=inbound_msg.id,
                        customer_phone_masked=mask_phone(customer_phone),
                        details={"error": safe_error, "transcription_ms": transcription_time_ms},
                    )
                    raise
                transcription_time_ms = int((time.monotonic() - t_start) * 1000)

                text_to_process = transcription.text
                language = transcription.language
                dialect = transcription.dialect

                await self._customer_repo.update_language(customer.id, language, dialect)
                await self._message_repo.save_transcription(
                    message_id=inbound_msg.id,
                    audio_url="",
                    transcript=text_to_process or "",
                    language=language,
                    dialect=dialect,
                    confidence=transcription.transcription_confidence,
                    duration=transcription.duration_seconds,
                )
                await emit_system_event(
                    event_type="transcription_completed",
                    event_level="info",
                    component="speech",
                    summary="Voice transcription completed.",
                    event_status="ok",
                    conversation_id=conversation.id,
                    message_id=inbound_msg.id,
                    customer_phone_masked=mask_phone(customer_phone),
                    details={
                        "language": language,
                        "dialect": dialect,
                        "confidence": transcription.transcription_confidence,
                        "duration_seconds": transcription.duration_seconds,
                        "transcription_ms": transcription_time_ms,
                    },
                )
            elif message_type == "image" and not text_to_process:
                text_to_process = ""

            if not text_to_process:
                await self._customer_repo.update_last_seen(customer.id)
                return ProcessingResult(
                    success=True,
                    response_sent=False,
                    response_text=None,
                    response_type="none",
                    handoff_created=False,
                    handoff_id=None,
                    error=None,
                    total_time_ms=int((time.monotonic() - wall_start) * 1000),
                    transcription_time_ms=transcription_time_ms,
                    ai_time_ms=None,
                )

            # -- Step 5: Single Claude call with tools ---------------------------
            ai_start = time.monotonic()

            recent_messages = await self._message_repo.get_recent(
                conversation.id, limit=10
            )
            history = _messages_to_history(recent_messages)

            system_prompt = build_system_prompt(
                store_config=self._store_config,
                language=language,
                dialect=dialect,
            )

            # Add current message to history
            messages = list(history)
            messages.append({"role": "user", "content": text_to_process})

            try:
                await emit_system_event(
                    event_type="claude_started",
                    event_level="info",
                    component="claude",
                    summary="Claude generation started.",
                    event_status="processing",
                    conversation_id=conversation.id,
                    message_id=inbound_msg.id,
                    customer_phone_masked=mask_phone(customer_phone),
                )
                tool_result = await self._claude.complete_with_tools(
                    system=system_prompt,
                    messages=messages,
                    tools=TOOLS,
                    tool_executor=self._tool_executor,
                )
            except Exception as exc:
                ai_time_ms = int((time.monotonic() - ai_start) * 1000)
                safe_error = summarize_exception_for_operations(exc)
                logger.warning(
                    "claude_unavailable_fallback_to_handoff",
                    customer_phone=mask_phone(customer_phone),
                    error=safe_error,
                )
                await emit_system_event(
                    event_type="claude_failed",
                    event_level="warning",
                    component="claude",
                    summary="Claude generation failed; using fallback handoff path.",
                    event_status="fallback",
                    conversation_id=conversation.id,
                    message_id=inbound_msg.id,
                    customer_phone_masked=mask_phone(customer_phone),
                    details={"error": safe_error, "ai_time_ms": ai_time_ms},
                )
                fallback = await self._execute_failure_handoff(
                    customer=customer,
                    conversation=conversation,
                    language=language,
                    reason="assistant_unavailable",
                    summary=(
                        "Automatic reply generation is temporarily unavailable. "
                        "The conversation has been routed for human follow-up."
                    ),
                )
                await self._customer_repo.update_last_seen(customer.id)
                return ProcessingResult(
                    success=True,
                    response_sent=fallback[2],
                    response_text=_failure_ack(language, self._store_config),
                    response_type=fallback[3],
                    handoff_created=fallback[0],
                    handoff_id=fallback[1],
                    error=None,
                    total_time_ms=int((time.monotonic() - wall_start) * 1000),
                    transcription_time_ms=transcription_time_ms,
                    ai_time_ms=ai_time_ms,
                )
            ai_time_ms = int((time.monotonic() - ai_start) * 1000)
            await emit_system_event(
                event_type="claude_completed",
                event_level="info",
                component="claude",
                summary="Claude generation completed.",
                event_status="ok",
                conversation_id=conversation.id,
                message_id=inbound_msg.id,
                customer_phone_masked=mask_phone(customer_phone),
                details={
                    "ai_time_ms": ai_time_ms,
                    "tool_calls": len(tool_result.tool_calls_log),
                    "escalated": tool_result.escalated,
                },
            )
            await self._conversation_repo.increment_ai_response_count(conversation.id)

            # -- Step 6: Execute result ------------------------------------------
            handoff_created = False
            handoff_id: uuid.UUID | None = None
            response_sent = False
            response_type: Literal["text", "voice", "none"] = "none"

            if tool_result.escalated:
                handoff_created, handoff_id, response_sent, response_type = (
                    await self._execute_handoff(
                        customer=customer,
                        conversation=conversation,
                        tool_result=tool_result,
                        language=language,
                    )
                )
            else:
                response_sent, response_type = await self._execute_auto_send(
                    customer=customer,
                    conversation=conversation,
                    generated_text=tool_result.response_text,
                    message_type=message_type,
                    language=language,
                )

            # -- Step 7: Update last seen ----------------------------------------
            await self._customer_repo.update_last_seen(customer.id)

            logger.info(
                "message_processed",
                customer_phone=mask_phone(customer_phone),
                action="handoff" if tool_result.escalated else "auto_send",
                response_sent=response_sent,
                handoff_created=handoff_created,
                tool_calls=len(tool_result.tool_calls_log),
                total_ms=int((time.monotonic() - wall_start) * 1000),
            )

            return ProcessingResult(
                success=True,
                response_sent=response_sent,
                response_text=tool_result.response_text,
                response_type=response_type,
                handoff_created=handoff_created,
                handoff_id=handoff_id,
                error=None,
                total_time_ms=int((time.monotonic() - wall_start) * 1000),
                transcription_time_ms=transcription_time_ms,
                ai_time_ms=ai_time_ms,
            )

        except Exception as exc:
            safe_error = summarize_exception_for_operations(exc)
            logger.error("orchestrator_error", error=safe_error, exc_info=True)
            if conversation is not None:
                await emit_system_event(
                    event_type="message_processing_failed",
                    event_level="error",
                    component="orchestrator",
                    summary="Conversation orchestration failed.",
                    event_status="failed",
                    conversation_id=conversation.id,
                    customer_phone_masked=mask_phone(customer_phone),
                    details={"error": safe_error},
                )
            return ProcessingResult(
                success=False,
                response_sent=False,
                response_text=None,
                response_type="none",
                handoff_created=False,
                handoff_id=None,
                error=safe_error,
                total_time_ms=int((time.monotonic() - wall_start) * 1000),
                transcription_time_ms=transcription_time_ms,
                ai_time_ms=ai_time_ms,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _execute_handoff(
        self,
        customer,
        conversation,
        tool_result: ToolCompletionResult,
        language: str,
    ) -> tuple[bool, uuid.UUID | None, bool, Literal["text", "voice", "none"]]:
        """Create a handoff record, update conversation status, send ACK."""
        summary = tool_result.escalation_summary or "Escalated by AI assistant"

        handoff = await self._handoff_repo.create(
            conversation_id=conversation.id,
            store_id=self._store_id,
            reason=tool_result.escalation_reason or "unknown",
            context_summary=summary,
            suggested_response=tool_result.response_text,
            priority=tool_result.escalation_priority,
        )
        await self._conversation_repo.update_status(
            conversation.id, ConversationStatus.human_takeover
        )

        # Send acknowledgment
        ack = _handoff_ack(language)
        send_result = await self._whatsapp.send_text(
            customer.phone_number, ack
        )
        response_sent = False
        if send_result.success:
            await self._message_repo.save_outbound(
                conversation_id=conversation.id,
                customer_id=customer.id,
                message_type="text",
                content=ack,
                whatsapp_message_id=send_result.message_id,
            )
            response_sent = True
        await emit_system_event(
            event_type="handoff_created",
            event_level="warning",
            component="orchestrator",
            summary="Conversation escalated for human attention.",
            event_status="pending",
            conversation_id=conversation.id,
            handoff_id=handoff.id,
            customer_phone_masked=mask_phone(customer.phone_number),
            details={"reason": tool_result.escalation_reason, "priority": tool_result.escalation_priority},
        )

        return True, handoff.id, response_sent, "text"

    async def _execute_failure_handoff(
        self,
        customer,
        conversation,
        language: str,
        reason: str,
        summary: str,
    ) -> tuple[bool, uuid.UUID | None, bool, Literal["text", "voice", "none"]]:
        """Create a handoff and send a safe fallback reply when automation is unavailable."""
        handoff = await self._handoff_repo.create(
            conversation_id=conversation.id,
            store_id=self._store_id,
            reason=reason,
            context_summary=summary,
            suggested_response=_failure_ack(language, self._store_config),
            priority=2,
        )

        response_sent = False
        ack = _failure_ack(language, self._store_config)
        send_result = await self._whatsapp.send_text(customer.phone_number, ack)
        if send_result.success:
            await self._message_repo.save_outbound(
                conversation_id=conversation.id,
                customer_id=customer.id,
                message_type="text",
                content=ack,
                whatsapp_message_id=send_result.message_id,
            )
            response_sent = True
        await emit_system_event(
            event_type="handoff_created",
            event_level="warning",
            component="orchestrator",
            summary="Fallback handoff created because automation was unavailable.",
            event_status="pending",
            conversation_id=conversation.id,
            handoff_id=handoff.id,
            customer_phone_masked=mask_phone(customer.phone_number),
            details={"reason": reason, "priority": 2},
        )

        return True, handoff.id, response_sent, "text"

    async def _execute_auto_send(
        self,
        customer,
        conversation,
        generated_text: str,
        message_type: str,
        language: str,
    ) -> tuple[bool, Literal["text", "voice", "none"]]:
        """Send the generated response. Prefer voice if input was voice and TTS ready."""
        # Try voice response
        if message_type == "voice" and self._tts and self._tts.is_configured:
            try:
                audio_url = await self._tts.generate(generated_text, language)
                if audio_url:
                    send_result = await self._whatsapp.send_voice(
                        customer.phone_number, audio_url
                    )
                    if send_result.success:
                        await self._message_repo.save_outbound(
                            conversation_id=conversation.id,
                            customer_id=customer.id,
                            message_type="voice",
                            content=generated_text,
                            media_url=audio_url,
                            whatsapp_message_id=send_result.message_id,
                        )
                        return True, "voice"
            except Exception as exc:
                logger.warning(
                    "tts_failed_falling_back_to_text",
                    error=summarize_exception_for_operations(exc),
                )

        # Text response (default)
        decision = self._outbound_policy.evaluate_freeform_send(
            last_customer_message_at=datetime.now(timezone.utc),
        )
        if not decision.allowed:
            logger.warning(
                "whatsapp_policy_blocked_auto_send",
                customer_phone=mask_phone(customer.phone_number),
                reason=decision.reason,
            )
            await emit_system_event(
                event_type="whatsapp_policy_blocked",
                event_level="warning",
                component="whatsapp",
                summary="Outbound free-form reply was blocked by policy.",
                event_status="blocked",
                conversation_id=conversation.id,
                customer_phone_masked=mask_phone(customer.phone_number),
                details={"reason": decision.reason},
            )
            return False, "none"

        send_result = await self._whatsapp.send_text(
            customer.phone_number, generated_text
        )
        if send_result.success:
            await self._message_repo.save_outbound(
                conversation_id=conversation.id,
                customer_id=customer.id,
                message_type="text",
                content=generated_text,
                whatsapp_message_id=send_result.message_id,
            )
            return True, "text"

        return False, "none"


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _messages_to_history(messages: list[Message]) -> list[dict]:
    """Convert recent Message ORM rows to the role/content format Claude uses."""
    history = []
    for msg in messages:
        if not msg.content:
            continue
        role = "user" if msg.direction == MessageDirection.inbound else "assistant"
        history.append({"role": role, "content": msg.content})
    return history


def _handoff_ack(language: str) -> str:
    """Return a short handoff acknowledgment in the customer's language."""
    acks = {
        "ml": "\u0d1e\u0d19\u0d4d\u0d19\u0d33\u0d41\u0d1f\u0d46 \u0d1f\u0d40\u0d02 \u0d09\u0d1f\u0d7b \u0d2c\u0d28\u0d4d\u0d27\u0d2a\u0d4d\u0d2a\u0d46\u0d1f\u0d41\u0d02. \u2728",
        "ta": "\u0b8e\u0b99\u0bcd\u0b95\u0bb3\u0bcd \u0b95\u0bc1\u0bb4\u0bc1 \u0bb5\u0bbf\u0bb0\u0bc8\u0bb5\u0bbf\u0bb2\u0bcd \u0ba4\u0bca\u0b9f\u0bb0\u0bcd\u0baa\u0bc1 \u0b95\u0bca\u0bb3\u0bcd\u0bb5\u0bbe\u0bb0\u0bcd\u0b95\u0bb3\u0bcd. \u2728",
    }
    return acks.get(language, "Our team will reach out to you shortly. \u2728")


def _failure_ack(language: str, store_config: dict | None = None) -> str:
    """Return a short fallback when the assistant is temporarily unavailable."""
    configured = (
        ((store_config or {}).get("fallback_messages") or {})
        .get("assistant_unavailable", {})
    )
    if isinstance(configured, dict):
        message = configured.get(language) or configured.get("en")
        if isinstance(message, str) and message:
            return message

    acks = {
        "ml": "\u0d15\u0d4d\u0d37\u0d2e\u0d3f\u0d15\u0d4d\u0d15\u0d23\u0d02, \u0d07\u0d2a\u0d4d\u0d2a\u0d4b\u0d7e \u0d0e\u0d28\u0d4d\u0d31\u0d46 \u0d38\u0d39\u0d3e\u0d2f\u0d3f \u0d2a\u0d4d\u0d30\u0d24\u0d3f\u0d15\u0d30\u0d3f\u0d15\u0d4d\u0d15\u0d3e\u0d7b \u0d15\u0d34\u0d3f\u0d2f\u0d41\u0d28\u0d4d\u0d28\u0d3f\u0d32\u0d4d\u0d32. \u0d28\u0d2e\u0d4d\u0d2e\u0d41\u0d1f\u0d46 \u0d1f\u0d40\u0d02 \u0d09\u0d1f\u0d7b \u0d2c\u0d28\u0d4d\u0d27\u0d2a\u0d4d\u0d2a\u0d46\u0d1f\u0d41\u0d02. \u2728",
        "ta": "\u0bae\u0ba9\u0bcd\u0ba9\u0bbf\u0b95\u0bcd\u0b95\u0bb5\u0bc1\u0bae\u0bcd, \u0b87\u0baa\u0bcd\u0baa\u0bcb\u0ba4\u0bc1 \u0b8e\u0ba9\u0bcd \u0b89\u0ba4\u0bb5\u0bbf\u0baf\u0bbe\u0bb3\u0bb0\u0bbe\u0bb2\u0bcd \u0baa\u0ba4\u0bbf\u0bb2\u0bb3\u0bbf\u0b95\u0bcd\u0b95 \u0bae\u0bc1\u0b9f\u0bbf\u0baf\u0bb5\u0bbf\u0bb2\u0bcd\u0bb2\u0bc8. \u0b8e\u0b99\u0bcd\u0b95\u0bb3\u0bcd \u0b95\u0bc1\u0bb4\u0bc1 \u0bb5\u0bbf\u0bb0\u0bc8\u0bb5\u0bbf\u0bb2\u0bcd \u0ba4\u0bca\u0b9f\u0bb0\u0bcd\u0baa\u0bc1 \u0b95\u0bca\u0bb3\u0bcd\u0bb5\u0bbe\u0bb0\u0bcd\u0b95\u0bb3\u0bcd. \u2728",
    }
    return acks.get(
        language,
        "Sorry, our assistant is temporarily unavailable. Our team will reach out shortly. \u2728",
    )
