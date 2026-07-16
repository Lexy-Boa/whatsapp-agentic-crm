# WhatsApp Business API Setup (Meta Cloud API)

## 1. Create the Meta App

1. Open [Meta for Developers](https://developers.facebook.com/).
2. Create or select the app that owns the WhatsApp integration.
3. Add the **WhatsApp** product.
4. In **API Setup**, collect:
   - access token
   - phone number ID
   - business account ID

Put them in `.env`:

```bash
WHATSAPP_ACCESS_TOKEN=your_meta_cloud_api_access_token
WHATSAPP_PHONE_NUMBER_ID=100320015621xxxx
WHATSAPP_BUSINESS_ACCOUNT_ID=946334921xxxxx
WHATSAPP_PHONE_NUMBER=+919876543210
```

## 2. Configure Webhook Security

Set these values in `.env`:

```bash
WHATSAPP_VERIFY_TOKEN=my-secret-verify-token
WHATSAPP_APP_SECRET=your_meta_app_secret
```

The app uses:
- `GET /webhook` for verification
- `POST /webhook` for inbound delivery
- `X-Hub-Signature-256` for request verification

## 3. Register the Webhook in Meta

1. Open the WhatsApp webhook configuration in the Meta app dashboard.
2. Set callback URL to `https://your-domain.com/webhook`.
3. Set verify token to match `WHATSAPP_VERIFY_TOKEN`.
4. Complete the verification handshake.

For local testing:

```bash
ngrok http 8000
```

Use the public HTTPS URL from ngrok as the callback URL.

## 4. Manual Verification Test

```bash
curl "https://your-domain.com/webhook?hub.mode=subscribe&hub.verify_token=my-secret-verify-token&hub.challenge=test123"
```

Expected response:

```text
test123
```

## 5. Connection Test

```bash
docker compose exec app python -m scripts.health_check --whatsapp
```

To send a test message to an approved test number:

```bash
docker compose exec app python -m scripts.send_test_message \
  --to "+919876543210" \
  --text "Hello! This is a test message from DemoBoutique."
```

## Troubleshooting

| Error | Fix |
|---|---|
| `403` on verification | `WHATSAPP_VERIFY_TOKEN` does not match Meta config |
| `403` on inbound webhook | signature validation failing or app secret wrong |
| `401` or `403` from Graph API | access token missing, expired, or missing permissions |
| Webhook unreachable | endpoint must be public HTTPS |
| Messages queue but no reply | check Redis, worker health, and `ANTHROPIC_API_KEY` |

## Message Flow

```text
Customer -> Meta Cloud API -> POST /webhook -> Orchestrator -> Claude -> Meta Cloud API -> Customer
```
