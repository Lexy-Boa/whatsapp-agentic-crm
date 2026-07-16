from __future__ import annotations

import json

import pytest

from src.workers.queue import (
    DEAD_LETTER_QUEUE_KEY,
    PROCESSING_QUEUE_KEY,
    PROCESSING_STARTED_HASH_KEY,
    QUEUE_KEY,
    ack_message,
    claim_message,
    enqueue_message,
    move_to_dead_letter,
    recover_stale_processing_messages,
)


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def blmove(
        self,
        source: str,
        destination: str,
        *,
        timeout: int,
        src: str,
        dest: str,
    ) -> str | None:
        del timeout, src, dest
        items = self.lists.setdefault(source, [])
        if not items:
            return None
        value = items.pop(0)
        self.lists.setdefault(destination, []).append(value)
        return value

    async def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def hdel(self, key: str, field: str) -> None:
        self.hashes.get(key, {}).pop(field, None)

    async def lrem(self, key: str, count: int, value: str) -> None:
        items = self.lists.setdefault(key, [])
        removed = 0
        remaining: list[str] = []
        for item in items:
            if item == value and removed < count:
                removed += 1
                continue
            remaining.append(item)
        self.lists[key] = remaining

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        if end == -1:
            return items[start:]
        return items[start : end + 1]


@pytest.mark.asyncio
async def test_claim_message_moves_payload_to_processing_queue(monkeypatch):
    redis = FakeRedis()
    payload = await enqueue_message(
        redis,
        {"whatsapp_message_id": "wamid.001", "from_phone": "919876543210"},
    )

    monkeypatch.setattr("src.workers.queue.time.time", lambda: 1000)
    claimed = await claim_message(redis, timeout=1)

    assert claimed == payload
    assert redis.lists[QUEUE_KEY] == []
    assert redis.lists[PROCESSING_QUEUE_KEY] == [payload]
    assert redis.hashes[PROCESSING_STARTED_HASH_KEY]["msg:wamid.001"] == "1000"


@pytest.mark.asyncio
async def test_ack_message_removes_payload_from_processing(monkeypatch):
    redis = FakeRedis()
    payload = await enqueue_message(
        redis,
        {"whatsapp_message_id": "wamid.ack", "from_phone": "919876543210"},
    )
    monkeypatch.setattr("src.workers.queue.time.time", lambda: 1000)
    await claim_message(redis, timeout=1)

    await ack_message(redis, payload)

    assert redis.lists[PROCESSING_QUEUE_KEY] == []
    assert redis.hashes[PROCESSING_STARTED_HASH_KEY] == {}


@pytest.mark.asyncio
async def test_move_to_dead_letter_wraps_payload_with_error():
    redis = FakeRedis()
    payload = json.dumps({"whatsapp_message_id": "wamid.dead", "from_phone": "919876543210"})
    redis.lists[PROCESSING_QUEUE_KEY] = [payload]
    redis.hashes[PROCESSING_STARTED_HASH_KEY] = {"msg:wamid.dead": "1000"}

    await move_to_dead_letter(redis, payload, "processing_failed")

    assert redis.lists[PROCESSING_QUEUE_KEY] == []
    dead_letter = json.loads(redis.lists[DEAD_LETTER_QUEUE_KEY][0])
    assert dead_letter["error"] == "processing_failed"
    assert dead_letter["payload"] == payload


@pytest.mark.asyncio
async def test_move_to_dead_letter_redacts_secrets_from_error():
    redis = FakeRedis()
    payload = json.dumps({"whatsapp_message_id": "wamid.secret", "from_phone": "919876543210"})
    redis.lists[PROCESSING_QUEUE_KEY] = [payload]
    redis.hashes[PROCESSING_STARTED_HASH_KEY] = {"msg:wamid.secret": "1000"}

    await move_to_dead_letter(
        redis,
        payload,
        "failed for +91 79946 85550 using EAAabcdefghijklmnopqrstuvwxyz1234567890",
    )

    dead_letter = json.loads(redis.lists[DEAD_LETTER_QUEUE_KEY][0])
    assert "79946 85550" not in dead_letter["error"]
    assert "EAAabcdefghijklmnopqrstuvwxyz1234567890" not in dead_letter["error"]
    assert "[REDACTED_SECRET]" in dead_letter["error"]


@pytest.mark.asyncio
async def test_recover_stale_processing_messages_requeues_payload(monkeypatch):
    redis = FakeRedis()
    original = json.dumps(
        {
            "whatsapp_message_id": "wamid.retry",
            "from_phone": "919876543210",
            "recovery_attempts": 0,
        }
    )
    redis.lists[PROCESSING_QUEUE_KEY] = [original]
    redis.hashes[PROCESSING_STARTED_HASH_KEY] = {"msg:wamid.retry": "1000"}

    monkeypatch.setattr("src.workers.queue.time.time", lambda: 1100)
    recovered = await recover_stale_processing_messages(
        redis,
        stale_after_seconds=30,
        max_recovery_attempts=3,
    )

    assert recovered == 1
    assert redis.lists[PROCESSING_QUEUE_KEY] == []
    requeued = json.loads(redis.lists[QUEUE_KEY][0])
    assert requeued["recovery_attempts"] == 1
    assert requeued["recovered_at"] == 1100


@pytest.mark.asyncio
async def test_recover_stale_processing_messages_dead_letters_after_max_attempts(monkeypatch):
    redis = FakeRedis()
    original = json.dumps(
        {
            "whatsapp_message_id": "wamid.exhausted",
            "from_phone": "919876543210",
            "recovery_attempts": 3,
        }
    )
    redis.lists[PROCESSING_QUEUE_KEY] = [original]
    redis.hashes[PROCESSING_STARTED_HASH_KEY] = {"msg:wamid.exhausted": "1000"}

    monkeypatch.setattr("src.workers.queue.time.time", lambda: 1100)
    recovered = await recover_stale_processing_messages(
        redis,
        stale_after_seconds=30,
        max_recovery_attempts=3,
    )

    assert recovered == 1
    assert redis.lists[PROCESSING_QUEUE_KEY] == []
    dead_letter = json.loads(redis.lists[DEAD_LETTER_QUEUE_KEY][0])
    assert dead_letter["error"] == "stale_processing_retry_exhausted"
