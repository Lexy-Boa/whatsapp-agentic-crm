"""
Background worker that processes WhatsApp messages from the Redis queue.

The webhook handler pushes serialised message data onto the Redis queue
``wa:queue:messages`` and returns 200 immediately. This worker claims
messages into a processing queue and runs the full orchestration pipeline.

Usage (run from project root inside the Docker container):
    python -m src.workers.message_processor
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

import structlog

from src.config import get_settings
from src.core.privacy import mask_phone, summarize_exception_for_operations
from src.db.postgres import close_db, get_session, init_db
from src.db.redis_client import close_redis, get_redis, init_redis
from src.db.vector_store import VectorStore
from src.services.observability.events import emit_system_event
from src.services.whatsapp.policy import WhatsAppPolicy
from src.workers.queue import (
    ack_message,
    claim_message,
    move_to_dead_letter,
    recover_stale_processing_messages,
)

logger = structlog.get_logger(__name__)

POLL_TIMEOUT = 5  # seconds to block while waiting to claim a queued message


class MessageProcessorWorker:
    """
    Claim messages from Redis and process each one via the orchestrator.

    Services are created once in run() and reused across messages (B3 fix).
    The worker runs indefinitely; stop it with SIGINT / SIGTERM.
    """

    def __init__(self, store_id: uuid.UUID) -> None:
        self._store_id = store_id
        self._running = False
        self._last_recovery_at = 0.0

    async def run(self) -> None:
        """Main worker loop — blocks until stopped."""
        logger.info("worker_starting", store_id=str(self._store_id))
        self._running = True

        await init_db()
        await init_redis()
        await emit_system_event(
            event_type="worker_started",
            event_level="info",
            component="worker",
            summary="Message processor worker started.",
            event_status="ok",
            details={"store_id": str(self._store_id)},
        )

        vector_store = VectorStore()
        await vector_store.initialize()

        # Create long-lived services once (B3: service reuse)
        from src.services.ai.claude_client import ClaudeClient
        from src.services.ai.embeddings import EmbeddingService
        from src.services.speech.transcriber import VoiceTranscriber
        from src.services.whatsapp.client import WhatsAppClient

        settings = get_settings()
        claude_client = ClaudeClient()
        whatsapp_client = WhatsAppClient(access_token=settings.whatsapp_access_token, phone_number_id=settings.whatsapp_phone_number_id)
        transcriber = VoiceTranscriber()
        embedding_service = EmbeddingService()
        outbound_policy = WhatsAppPolicy(
            mode=settings.whatsapp_policy_mode,  # type: ignore[arg-type]
            customer_service_window_hours=settings.whatsapp_customer_service_window_hours,
        )

        try:
            while self._running:
                await self._recover_if_needed(settings)
                await self._poll(
                    vector_store=vector_store,
                    claude_client=claude_client,
                    whatsapp_client=whatsapp_client,
                    transcriber=transcriber,
                    embedding_service=embedding_service,
                    outbound_policy=outbound_policy,
                )
        finally:
            await claude_client.close()
            await whatsapp_client.close()
            await close_db()
            await close_redis()
            await vector_store.close()
            logger.info("worker_stopped")
            await emit_system_event(
                event_type="worker_stopped",
                event_level="warning",
                component="worker",
                summary="Message processor worker stopped.",
                event_status="stopped",
                details={"store_id": str(self._store_id)},
            )

    async def _poll(
        self,
        vector_store: VectorStore,
        claude_client,
        whatsapp_client,
        transcriber,
        embedding_service,
        outbound_policy,
    ) -> None:
        """Block-pop one message from Redis and process it."""
        redis = get_redis()
        payload = await claim_message(redis, timeout=POLL_TIMEOUT)
        if payload is None:
            return  # timeout, nothing in queue

        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as exc:
            safe_error = summarize_exception_for_operations(exc)
            logger.error("worker_invalid_payload", error=safe_error)
            await emit_system_event(
                event_type="message_processing_failed",
                event_level="error",
                component="worker",
                summary="Worker rejected an invalid queue payload.",
                event_status="failed",
                details={"error": safe_error},
            )
            await move_to_dead_letter(redis, payload, "invalid_json_payload")
            return

        await self._process_one(
            data,
            payload=payload,
            vector_store=vector_store,
            claude_client=claude_client,
            whatsapp_client=whatsapp_client,
            transcriber=transcriber,
            embedding_service=embedding_service,
            outbound_policy=outbound_policy,
        )

    async def _process_one(
        self,
        data: dict,
        payload: str,
        vector_store: VectorStore,
        claude_client,
        whatsapp_client,
        transcriber,
        embedding_service,
        outbound_policy,
    ) -> None:
        """Run the full orchestration pipeline for one queued message."""
        from src.core.orchestrator import ConversationOrchestrator
        from src.core.product_matcher import ProductMatcher
        from src.db.repositories.conversation_repo import ConversationRepository
        from src.db.repositories.customer_repo import CustomerRepository
        from src.db.repositories.handoff_repo import HandoffRepository
        from src.db.repositories.message_repo import MessageRepository
        from src.db.repositories.product_repo import ProductRepository
        from src.services.ai.response_generator import DEFAULT_STORE_CONFIG
        from src.services.ai.tool_executor import ToolExecutor

        from_phone: str = data.get("from_phone", "")
        message_type: str = data.get("message_type", "text")
        text: str | None = data.get("text")
        media_id: str | None = data.get("media_id")
        media_mime_type: str | None = data.get("media_mime_type")
        whatsapp_message_id: str | None = data.get("whatsapp_message_id")

        if not from_phone:
            logger.error("worker_missing_from_phone", whatsapp_message_id=whatsapp_message_id)
            await move_to_dead_letter(get_redis(), payload, "missing_from_phone")
            return

        logger.info(
            "worker_processing_message",
            from_phone=mask_phone(from_phone),
            message_type=message_type,
            whatsapp_message_id=whatsapp_message_id,
        )
        await emit_system_event(
            event_type="message_processing_started",
            event_level="info",
            component="worker",
            summary=f"Worker started processing {message_type} message.",
            event_status="processing",
            customer_phone_masked=mask_phone(from_phone),
            details={
                "whatsapp_message_id": whatsapp_message_id,
                "message_type": message_type,
            },
        )

        # Download media bytes if voice message
        media_bytes: bytes | None = None
        if message_type == "voice" and media_id:
            try:
                media_bytes, media_mime_type = await whatsapp_client.download_media(
                    media_id
                )
            except Exception as exc:
                safe_error = summarize_exception_for_operations(exc)
                logger.error("worker_media_download_failed", error=safe_error)
                await emit_system_event(
                    event_type="message_processing_failed",
                    event_level="error",
                    component="worker",
                    summary="Voice media download failed before orchestration.",
                    event_status="failed",
                    customer_phone_masked=mask_phone(from_phone),
                    details={"error": safe_error, "whatsapp_message_id": whatsapp_message_id},
                )
                await move_to_dead_letter(get_redis(), payload, f"media_download_failed:{safe_error}")
                return

        result = None
        async for session in get_session():
            product_repo = ProductRepository(session)
            customer_repo = CustomerRepository(session)
            conversation_repo = ConversationRepository(session)
            message_repo = MessageRepository(session)
            handoff_repo = HandoffRepository(session)

            product_matcher = ProductMatcher(
                embedding_service=embedding_service,
                vector_store=vector_store,
                product_repo=product_repo,
            )
            tool_executor = ToolExecutor(
                product_matcher=product_matcher,
                product_repo=product_repo,
                store_id=self._store_id,
            )

            orchestrator = ConversationOrchestrator(
                store_id=self._store_id,
                store_config=DEFAULT_STORE_CONFIG,
                whatsapp_client=whatsapp_client,
                transcriber=transcriber,
                claude_client=claude_client,
                tool_executor=tool_executor,
                tts=None,
                customer_repo=customer_repo,
                conversation_repo=conversation_repo,
                message_repo=message_repo,
                handoff_repo=handoff_repo,
                outbound_policy=outbound_policy,
            )

            result = await orchestrator.process_message(
                customer_phone=from_phone,
                message_type=message_type,  # type: ignore[arg-type]
                content=text,
                media_bytes=media_bytes,
                media_mime_type=media_mime_type,
                whatsapp_message_id=whatsapp_message_id,
            )

        if result and result.success:
            await ack_message(get_redis(), payload)
            logger.info(
                "worker_message_processed",
                from_phone=mask_phone(from_phone),
                response_sent=result.response_sent,
                handoff_created=result.handoff_created,
                total_ms=result.total_time_ms,
            )
            await emit_system_event(
                event_type="message_processed",
                event_level="info",
                component="worker",
                summary="Queued message processed successfully.",
                event_status="ok",
                customer_phone_masked=mask_phone(from_phone),
                details={
                    "whatsapp_message_id": whatsapp_message_id,
                    "response_sent": result.response_sent,
                    "handoff_created": result.handoff_created,
                    "total_ms": result.total_time_ms,
                },
            )
        elif result:
            safe_error = summarize_exception_for_operations(result.error or "processing_failed")
            await move_to_dead_letter(get_redis(), payload, safe_error)
            logger.error(
                "worker_message_failed",
                from_phone=mask_phone(from_phone),
                error=safe_error,
            )
            await emit_system_event(
                event_type="message_processing_failed",
                event_level="error",
                component="worker",
                summary="Queued message failed and was moved to the dead-letter queue.",
                event_status="failed",
                customer_phone_masked=mask_phone(from_phone),
                details={
                    "whatsapp_message_id": whatsapp_message_id,
                    "error": safe_error,
                },
            )

    async def _recover_if_needed(self, settings) -> None:
        now = time.monotonic()
        if now - self._last_recovery_at < settings.queue_recovery_interval_seconds:
            return

        self._last_recovery_at = now
        recovered = await recover_stale_processing_messages(
            get_redis(),
            stale_after_seconds=settings.queue_processing_timeout_seconds,
            max_recovery_attempts=settings.queue_max_recovery_attempts,
        )
        if recovered:
            logger.warning("worker_recovered_stale_messages", count=recovered)
            await emit_system_event(
                event_type="queue_recovered",
                event_level="warning",
                component="queue",
                summary=f"Recovered {recovered} stale queued message(s).",
                event_status="recovered",
                details={"count": recovered},
            )

    def stop(self) -> None:
        """Signal the worker to stop after the current message."""
        self._running = False


async def _main() -> None:
    settings = get_settings()
    store_id_str = settings.store_id
    if not store_id_str:
        logger.error("worker_no_store_id", hint="Set STORE_ID in .env")
        return

    try:
        store_id = uuid.UUID(store_id_str)
    except ValueError:
        logger.error("worker_invalid_store_id", value=store_id_str)
        return

    worker = MessageProcessorWorker(store_id=store_id)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(_main())
