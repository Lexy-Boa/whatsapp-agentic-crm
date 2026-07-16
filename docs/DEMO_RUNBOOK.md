# Demo Runbook

## Goal

Deliver a believable DemoBoutique demo that proves:
- multilingual replies
- voice-note handling
- product-aware recommendations
- inventory-aware responses
- policy-safe business answers
- human handoff behavior

The store's policy guardrails and owner-confirmation items live in
[`data/demo/demoboutique_business_profile.json`](../data/demo/demoboutique_business_profile.json).

## Prerequisites

- `GROQ_API_KEY`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_APP_SECRET`
- `STORE_ID`

## Setup

Start infrastructure:

```bash
docker compose up -d
docker compose exec app alembic upgrade head
```

Seed the demo catalog:

```bash
python -m scripts.setup_demo --store-id <uuid>
```

`setup_demo` now supports degraded setup. If Anthropic, Groq, or OpenAI are not
available yet, it still attempts to seed the mock catalog into Postgres and
prints what will be unavailable.

Review the local business profile before enabling smart replies for the owner:

```text
data/demo/demoboutique_business_profile.json
```

Run the no-credits policy evaluator before any paid smart-reply demo:

```bash
python -m scripts.evaluate_demo_policy
```

Expose the webhook temporarily:

```bash
ngrok http 8000
```

Set Meta webhook callback URL to:

```text
https://<your-tunnel-host>/webhook
```

## Demo Flows

### 1. Malayalam Voice Flow
- customer sends a Malayalam voice note
- app transcribes the note
- app replies in Malayalam

Verify with:

```bash
python -m scripts.test_full_pipeline --store-id <uuid> --phone +919876543210 --voice-file test_audio/test1.ogg
```

### 2. Budget Recommendation Flow
- customer asks for a saree for a wedding under a budget
- app recommends matching products from the mock catalog

Verify with:

```bash
python -m scripts.test_full_pipeline --store-id <uuid> --phone +919876543210 --message "Looking for a wedding saree under 10000"
```

### 3. Inventory Flow
- customer asks if a specific SKU is available
- app answers using product and stock data

Suggested prompt:

```text
Is DMB-3001 available now?
```

### 4. Handoff Flow
- customer reports a complaint or refund request
- app creates a handoff and acknowledges that a human will follow up

Suggested prompt:

```text
I received a damaged product and want a refund
```

### 5. Policy Guardrail Flow
- customer asks about an unconfirmed payment, COD, return, delivery, or store-hours detail
- app should not invent the answer
- app should say the DemoBoutique team will confirm and escalate if the decision affects money, delivery, or trust

Suggested prompt:

```text
Do you have COD and can I return this if it does not fit?
```

### 6. Control Room Owner Flow
- open `/control-room`
- watch activity, errors, conversations, and handoffs while messages arrive
- resolve a handoff
- take over a conversation
- release the conversation back to bot mode
- export the conversation as Markdown

## Acceptance Criteria

- inbound webhook reaches the app
- worker processes the message end-to-end
- voice transcription works
- reply is generated in the expected language
- at least one handoff path is visible and understandable
- operational logs show masked phone numbers only
- queue recovery prevents silent loss if the worker crashes mid-processing
- Avni Control Room shows fresh activity and lets the owner resolve/release at least one conversation
