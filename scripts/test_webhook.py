"""
Manual test script for the WhatsApp webhook endpoints.

Usage (with the app running via docker compose):
    python scripts/test_webhook.py

What it tests:
  1. GET /webhook - verification handshake
  2. POST /webhook - text message payload
  3. POST /webhook - voice message payload
  4. POST /webhook - duplicate message
  5. POST /webhook - status-only payload
  6. POST /webhook - bad signature (only if APP_SECRET is set)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import time

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_VERIFY_TOKEN = "test-verify-token"
DEFAULT_APP_SECRET = ""


def _meta_envelope(value: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "demo_waba_001",
                "changes": [
                    {
                        "field": "messages",
                        "value": value,
                    }
                ],
            }
        ],
    }


def _text_payload(msg_id: str, from_phone: str = "919876543210") -> dict:
    value = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "919876543210",
            "phone_number_id": "100320015621000",
        },
        "contacts": [{"profile": {"name": "Test Customer"}, "wa_id": from_phone}],
        "messages": [
            {
                "from": from_phone,
                "id": msg_id,
                "timestamp": str(int(time.time())),
                "type": "text",
                "text": {"body": "Hello, I want to order a saree"},
            }
        ],
    }
    return _meta_envelope(value)


def _voice_payload(msg_id: str, from_phone: str = "919876543210") -> dict:
    value = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "919876543210",
            "phone_number_id": "100320015621000",
        },
        "contacts": [{"profile": {"name": "Test Customer"}, "wa_id": from_phone}],
        "messages": [
            {
                "from": from_phone,
                "id": msg_id,
                "timestamp": str(int(time.time())),
                "type": "audio",
                "audio": {
                    "id": "media-id-abc123",
                    "mime_type": "audio/ogg; codecs=opus",
                },
            }
        ],
    }
    return _meta_envelope(value)


def _status_only_payload() -> dict:
    value = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "919876543210",
            "phone_number_id": "100320015621000",
        },
        "statuses": [
            {
                "id": "wamid.status123",
                "recipient_id": "919876543210",
                "status": "delivered",
                "timestamp": str(int(time.time())),
            }
        ],
    }
    return _meta_envelope(value)


def _compute_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def run_tests(*, base_url: str, verify_token: str, app_secret: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        passed = 0
        failed = 0

        print("\n[1] GET /webhook - verification handshake")
        resp = await client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": verify_token,
                "hub.challenge": "challenge_abc123",
            },
        )
        if resp.status_code == 200 and resp.text == "challenge_abc123":
            print(f"    PASS - got challenge back: {resp.text!r}")
            passed += 1
        else:
            print(f"    FAIL - status={resp.status_code} body={resp.text!r}")
            failed += 1

        print("\n[2] GET /webhook - wrong token -> 403")
        resp = await client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "challenge_xyz",
            },
        )
        if resp.status_code == 403:
            print("    PASS - got 403 as expected")
            passed += 1
        else:
            print(f"    FAIL - status={resp.status_code}")
            failed += 1

        print("\n[3] POST /webhook - text message")
        payload = _text_payload("wamid.text001")
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if app_secret:
            headers["X-Hub-Signature-256"] = _compute_signature(body, app_secret)

        resp = await client.post("/webhook", content=body, headers=headers)
        if resp.status_code == 200 and resp.json() == {"status": "ok"}:
            print(f"    PASS - {resp.json()}")
            passed += 1
        else:
            print(f"    FAIL - status={resp.status_code} body={resp.text!r}")
            failed += 1

        print("\n[4] POST /webhook - voice (audio) message")
        payload = _voice_payload("wamid.voice001")
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if app_secret:
            headers["X-Hub-Signature-256"] = _compute_signature(body, app_secret)

        resp = await client.post("/webhook", content=body, headers=headers)
        if resp.status_code == 200 and resp.json() == {"status": "ok"}:
            print(f"    PASS - {resp.json()}")
            passed += 1
        else:
            print(f"    FAIL - status={resp.status_code} body={resp.text!r}")
            failed += 1

        print("\n[5] POST /webhook - duplicate text message (same wamid.text001)")
        payload = _text_payload("wamid.text001")
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if app_secret:
            headers["X-Hub-Signature-256"] = _compute_signature(body, app_secret)

        resp = await client.post("/webhook", content=body, headers=headers)
        if resp.status_code == 200:
            print("    PASS - 200 returned; check logs for duplicate skip")
            passed += 1
        else:
            print(f"    FAIL - status={resp.status_code}")
            failed += 1

        print("\n[6] POST /webhook - status-only payload (delivery receipt)")
        payload = _status_only_payload()
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if app_secret:
            headers["X-Hub-Signature-256"] = _compute_signature(body, app_secret)

        resp = await client.post("/webhook", content=body, headers=headers)
        if resp.status_code == 200:
            print(f"    PASS - {resp.json()}")
            passed += 1
        else:
            print(f"    FAIL - status={resp.status_code} body={resp.text!r}")
            failed += 1

        if app_secret:
            print("\n[7] POST /webhook - tampered payload -> 403")
            payload = _text_payload("wamid.tampered001")
            body = json.dumps(payload).encode()
            resp = await client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": "sha256=deadbeef",
                },
            )
            if resp.status_code == 403:
                print("    PASS - got 403 as expected")
                passed += 1
            else:
                print(f"    FAIL - status={resp.status_code}")
                failed += 1
        else:
            print("\n[7] POST /webhook - bad signature test SKIPPED (APP_SECRET not set)")

        total = passed + failed
        print(f"\n{'=' * 50}")
        print(f"Results: {passed}/{total} passed", "PASS" if failed == 0 else "FAIL")
        if failed:
            print("Check that the app is running: docker compose up -d")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exercise the local WhatsApp webhook endpoints.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL for the running app.",
    )
    parser.add_argument(
        "--verify-token",
        default=DEFAULT_VERIFY_TOKEN,
        help="Expected webhook verify token.",
    )
    parser.add_argument(
        "--app-secret",
        default=DEFAULT_APP_SECRET,
        help="Optional app secret for signature verification tests.",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(
        run_tests(
            base_url=args.base_url,
            verify_token=args.verify_token,
            app_secret=args.app_secret,
        )
    )
