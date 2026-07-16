from __future__ import annotations

import hashlib
import json
import time

from redis.asyncio import Redis

from src.core.privacy import redact_operational_text

QUEUE_KEY = "wa:queue:messages"
PROCESSING_QUEUE_KEY = "wa:queue:messages:processing"
DEAD_LETTER_QUEUE_KEY = "wa:queue:messages:dead"
PROCESSING_STARTED_HASH_KEY = "wa:queue:messages:processing:started"


def _payload_token(payload: str) -> str:
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return f"raw:{hashlib.sha1(payload.encode('utf-8')).hexdigest()}"

    message_id = data.get("whatsapp_message_id")
    if message_id:
        return f"msg:{message_id}"

    return f"raw:{hashlib.sha1(payload.encode('utf-8')).hexdigest()}"


async def enqueue_message(redis: Redis, payload: dict | str) -> str:
    if isinstance(payload, dict):
        payload = json.dumps(payload)
    await redis.rpush(QUEUE_KEY, payload)
    return payload


async def claim_message(redis: Redis, timeout: int) -> str | None:
    payload = await redis.blmove(
        QUEUE_KEY,
        PROCESSING_QUEUE_KEY,
        timeout=timeout,
        src="LEFT",
        dest="RIGHT",
    )
    if payload is None:
        return None
    await redis.hset(PROCESSING_STARTED_HASH_KEY, _payload_token(payload), str(int(time.time())))
    return payload


async def ack_message(redis: Redis, payload: str) -> None:
    await redis.lrem(PROCESSING_QUEUE_KEY, 1, payload)
    await redis.hdel(PROCESSING_STARTED_HASH_KEY, _payload_token(payload))


async def move_to_dead_letter(redis: Redis, payload: str, error: str) -> None:
    await ack_message(redis, payload)
    dead_letter = {
        "error": redact_operational_text(error, max_length=160),
        "failed_at": int(time.time()),
        "payload": payload,
    }
    await redis.rpush(DEAD_LETTER_QUEUE_KEY, json.dumps(dead_letter))


async def recover_stale_processing_messages(
    redis: Redis,
    *,
    stale_after_seconds: int,
    max_recovery_attempts: int,
    limit: int = 50,
) -> int:
    recovered = 0
    now_ts = int(time.time())
    processing_payloads = await redis.lrange(PROCESSING_QUEUE_KEY, 0, limit - 1)

    for payload in processing_payloads:
        token = _payload_token(payload)
        started_raw = await redis.hget(PROCESSING_STARTED_HASH_KEY, token)
        started_at = int(started_raw) if started_raw else now_ts
        if now_ts - started_at < stale_after_seconds:
            continue

        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            await move_to_dead_letter(redis, payload, "stale_invalid_processing_payload")
            recovered += 1
            continue

        recoveries = int(parsed.get("recovery_attempts", 0)) + 1
        if recoveries > max_recovery_attempts:
            await move_to_dead_letter(redis, payload, "stale_processing_retry_exhausted")
            recovered += 1
            continue

        parsed["recovery_attempts"] = recoveries
        parsed["recovered_at"] = now_ts

        await ack_message(redis, payload)
        await enqueue_message(redis, parsed)
        recovered += 1

    return recovered
