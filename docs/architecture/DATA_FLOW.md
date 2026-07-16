# Data Flow - WhatsApp Fashion CRM

## Inbound Message Flow

```text
Customer (WhatsApp)
    |
    | HTTP POST (Meta Cloud API webhook)
    v
Webhook API (/webhook)
    - verify X-Hub-Signature-256
    - parse payload
    - enqueue work in Redis
    |
    v
Message Worker
    - dequeue message
    - run orchestrator
    |
    v
Orchestrator
    1. get or create customer and conversation
    2. persist inbound message
    3. short-circuit if human takeover is active
    4. transcribe voice if needed
    5. run Claude tool-use loop
    6. send WhatsApp reply or create handoff
    7. update counters and last-seen state
    |
    v
Customer (WhatsApp)
```

## Voice Message Sub-Flow

```text
Audio message
    |
    v
WhatsApp client downloads media from Meta Graph/CDN
    |
    v
Whisper transcription
    |
    v
Dialect detection / normalization
    |
    v
Orchestrator continues
```

## Claude Tool-Use Flow

Claude may call:
- `search_products`
- `check_inventory`
- `lookup_order`
- `escalate_to_human`

Tool results are fed back into the same loop until a final response or handoff
decision is produced.

## External APIs

| Service | Direction | Purpose |
|---|---|---|
| Meta WhatsApp Cloud API | Inbound + outbound | Messages, webhook delivery, media download |
| Anthropic Claude API | Outbound | Reasoning and tool use |
| Groq API | Outbound | Voice transcription |
| OpenAI API | Outbound | Product embeddings |
| Shopify Admin API | Outbound | Catalog and order data |
