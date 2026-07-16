from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


class FakeRedis:
    def __init__(self, *, is_new: bool = True) -> None:
        self.is_new = is_new
        self.set_calls: list[tuple[str, str, bool, int]] = []

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        self.set_calls.append((key, value, nx, ex))
        return self.is_new


def _signed_headers(body: bytes, secret: str) -> dict[str, str]:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}"}


def _payload(message_id: str = "wamid.test.1", text: str = "Hello Avni") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "917994685550",
                                    "timestamp": "1713160000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }


@pytest.fixture
async def webhook_client(monkeypatch):
    import src.api.webhooks.whatsapp as webhook

    monkeypatch.setattr(webhook.settings, "whatsapp_app_secret", "app-secret")
    monkeypatch.setattr(webhook.settings, "whatsapp_phone_number", "+15550001234")
    monkeypatch.setattr(webhook.settings, "store_id", "store-001")
    monkeypatch.setattr(webhook, "emit_system_event", AsyncMock())

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, webhook


async def test_webhook_post_accepts_valid_signed_text_and_queues_payload(
    webhook_client,
    monkeypatch,
):
    client, webhook = webhook_client
    body = json.dumps(_payload()).encode("utf-8")
    enqueue_mock = AsyncMock()

    monkeypatch.setattr(webhook, "get_redis", lambda: FakeRedis(is_new=True))
    monkeypatch.setattr(webhook, "enqueue_message", enqueue_mock)

    response = await client.post(
        "/webhook",
        content=body,
        headers=_signed_headers(body, "app-secret"),
    )

    assert response.status_code == 200
    enqueue_mock.assert_awaited_once()
    queued_payload = enqueue_mock.await_args.args[1]
    assert queued_payload["from_phone"] == "917994685550"
    assert queued_payload["message_type"] == "text"
    assert queued_payload["text"] == "Hello Avni"
    assert queued_payload["whatsapp_message_id"] == "wamid.test.1"


async def test_webhook_post_rejects_invalid_signature(webhook_client):
    client, _ = webhook_client
    body = json.dumps(_payload()).encode("utf-8")

    response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )

    assert response.status_code == 403


async def test_webhook_post_rejects_invalid_json(webhook_client, monkeypatch):
    client, webhook = webhook_client
    body = b"{not-json"
    monkeypatch.setattr(webhook.settings, "whatsapp_app_secret", "")

    response = await client.post("/webhook", content=body)

    assert response.status_code == 400


async def test_webhook_post_skips_duplicate_delivery(webhook_client, monkeypatch):
    client, webhook = webhook_client
    body = json.dumps(_payload(message_id="wamid.duplicate")).encode("utf-8")
    enqueue_mock = AsyncMock()

    monkeypatch.setattr(webhook, "get_redis", lambda: FakeRedis(is_new=False))
    monkeypatch.setattr(webhook, "enqueue_message", enqueue_mock)

    response = await client.post(
        "/webhook",
        content=body,
        headers=_signed_headers(body, "app-secret"),
    )

    assert response.status_code == 200
    enqueue_mock.assert_not_awaited()


async def test_webhook_post_operational_logs_do_not_include_raw_message_text(
    webhook_client,
    monkeypatch,
):
    client, webhook = webhook_client
    body = json.dumps(_payload(text="raw customer secret text")).encode("utf-8")
    logger_mock = MagicMock()

    monkeypatch.setattr(webhook, "get_redis", lambda: FakeRedis(is_new=True))
    monkeypatch.setattr(webhook, "enqueue_message", AsyncMock())
    monkeypatch.setattr(webhook, "logger", logger_mock)

    response = await client.post(
        "/webhook",
        content=body,
        headers=_signed_headers(body, "app-secret"),
    )

    assert response.status_code == 200
    assert "raw customer secret text" not in str(logger_mock.method_calls)
