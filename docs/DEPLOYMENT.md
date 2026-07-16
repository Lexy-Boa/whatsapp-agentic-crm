# Deployment Guide

## Prerequisites

- Docker and Docker Compose v2
- A public HTTPS domain for the webhook
- API credentials for:
  - [Anthropic](https://console.anthropic.com/)
  - [OpenAI](https://platform.openai.com/)
  - [Groq](https://console.groq.com/)
  - [Meta for Developers](https://developers.facebook.com/)
  - [Shopify](https://shopify.dev/docs/api/admin-rest)

## Environment Variables

Copy `.env.example` to `.env` and fill in every required value.

| Variable | Required | Description |
|---|---|---|
| `ENVIRONMENT` | Yes | `dev`, `staging`, or `prod` |
| `DEBUG` | No | `true` only in dev |
| `LOG_LEVEL` | No | logging level |
| `POSTGRES_HOST` | Yes | Postgres host |
| `POSTGRES_PORT` | No | default `5432` |
| `POSTGRES_USER` | Yes | Postgres username |
| `POSTGRES_PASSWORD` | Yes | Postgres password |
| `POSTGRES_DB` | Yes | database name |
| `REDIS_HOST` | Yes | Redis host |
| `REDIS_PORT` | No | default `6379` |
| `REDIS_PASSWORD` | No | required in prod if configured |
| `REDIS_DB` | No | default `0` |
| `QDRANT_HOST` | Yes | Qdrant host |
| `QDRANT_PORT` | No | default `6333` |
| `QDRANT_API_KEY` | No | required for Qdrant Cloud |
| `QDRANT_COLLECTION` | No | default `products` |
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `CLAUDE_MODEL` | No | default `claude-sonnet-4-6` |
| `CLAUDE_MAX_TOKENS` | No | default `4096` |
| `CLAUDE_TEMPERATURE` | No | default `0.7` |
| `GROQ_API_KEY` | No | required when using Groq for Whisper |
| `WHISPER_PROVIDER` | No | `groq` or `openai` |
| `WHISPER_MODEL` | No | default `whisper-large-v3-turbo` |
| `OPENAI_API_KEY` | Yes | embeddings key |
| `OPENAI_EMBEDDING_MODEL` | No | default `text-embedding-3-small` |
| `WHATSAPP_ACCESS_TOKEN` | Yes | Meta Cloud API bearer token |
| `WHATSAPP_PHONE_NUMBER_ID` | Yes | Meta phone number ID |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | Yes | Meta WABA ID |
| `WHATSAPP_PHONE_NUMBER` | Yes | business phone number |
| `WHATSAPP_VERIFY_TOKEN` | Yes | webhook verify token |
| `WHATSAPP_APP_SECRET` | Yes | webhook signature secret |
| `SHOPIFY_SHOP_DOMAIN` | Yes | shop domain |
| `SHOPIFY_ACCESS_TOKEN` | Yes | Shopify access token |
| `SHOPIFY_API_VERSION` | No | default `2024-01` |
| `STORE_ID` | Yes | default store UUID |
| `CORS_ORIGINS` | No | JSON array of allowed origins |

## Local Development

```bash
git clone <repo-url> && cd whatsapp-fashion-crm
cp .env.example .env
docker compose up -d
docker compose exec app alembic upgrade head
docker compose exec app python -m scripts.setup_store \
  --name "DemoBoutique" \
  --slug "demoboutique" \
  --shopify-domain "demoboutique.myshopify.com" \
  --shopify-token "shpat_xxxxx" \
  --whatsapp-phone "+919876543210"
docker compose exec app python -m scripts.health_check
curl http://localhost:8000/health
```

## Production Deployment

Supported patterns remain the same:
- Railway
- Render
- VPS with Docker Compose

For any platform:
- run migrations before traffic
- configure the public webhook at `https://your-domain.com/webhook`
- set the webhook in the Meta app dashboard
- ensure the verify token matches `WHATSAPP_VERIFY_TOKEN`

## Webhook Setup

For local development:

```bash
ngrok http 8000
```

For production, use:

```text
https://your-domain.com/webhook
```

Set that callback URL in the Meta app's WhatsApp webhook configuration.

## Monitoring

```bash
docker compose logs -f app
docker compose exec app python -m scripts.health_check
curl https://your-domain.com/health
```
