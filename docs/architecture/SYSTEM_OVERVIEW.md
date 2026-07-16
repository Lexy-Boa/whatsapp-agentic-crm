# System Overview - WhatsApp Fashion CRM

See also `knowledge/ARCHITECTURE.md` for the decision layer.

## Purpose

An AI-powered CRM for fashion retail conversations over WhatsApp. The system
handles multilingual text, voice notes, product search, and human handoff.

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| API | FastAPI | REST endpoints and webhook |
| Database | PostgreSQL | conversations, products, customers, orders |
| Cache / Queue | Redis | queueing and short-lived state |
| Vector Search | Qdrant | semantic product search |
| AI - Reasoning | Anthropic Claude | tool-use response generation |
| AI - Speech | Groq Whisper | transcription |
| AI - Embeddings | OpenAI text-embedding-3-small | search vectors |
| Integration | Shopify | catalog sync |
| Messaging | Meta WhatsApp Cloud API | inbound and outbound messages |

## Service Layout

```text
src/
├── api/
│   ├── agent/        # dashboard + human handoff endpoints
│   └── webhooks/     # Meta Cloud API webhook receiver
├── core/
│   ├── orchestrator.py
│   ├── product_matcher.py
│   └── context_builder.py
├── db/
│   ├── models/
│   ├── repositories/
│   └── vector_store.py
├── services/
│   ├── ai/
│   ├── shopify/
│   ├── speech/
│   └── whatsapp/     # Meta Cloud API client + message parsing
└── workers/
    └── message_processor.py
```

## Key Notes

- webhook verification and inbound delivery happen at `/webhook`
- the webhook validates `X-Hub-Signature-256`
- business logic is asynchronous and queue-backed
- the WhatsApp transport uses the Meta Cloud API env surface defined in `.env.example`

## Core Env Surface

```text
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
GROQ_API_KEY=...
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_BUSINESS_ACCOUNT_ID=...
WHATSAPP_PHONE_NUMBER=...
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_APP_SECRET=...
STORE_ID=...
```
