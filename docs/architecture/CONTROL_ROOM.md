# Avni Control Room - Architecture Decisions

## Purpose

Avni Control Room is an observability and owner-operations interface for a
single-brand Avni deployment.

It is not a staff dashboard, agent workspace, or multi-user CRM admin product.
Its first job is to show what the Avni agent is doing, whether the runtime is
healthy, where failures are happening, and what conversation and handoff state
exists in the system.

## Product Truth

- Avni is single-tenant per deployment.
- One deployment serves one business owner, one brand, one WhatsApp business
  number, and one operational database.
- Multi-tenant SaaS concerns are explicitly out of scope for the current phase.

## What Control Room Is

Control Room is an owner-facing operations console.

V1 scope:
- agent runtime status: `online`, `degraded`, `offline`
- last successful activity time
- queue depth
- message throughput counters
- auto-reply count
- human handoff count
- failed-processing count
- average processing time
- open conversation count
- human-takeover conversation count
- recent error feed
- recent handoff feed
- recent activity timeline
- export actions for selected datasets in CSV and Markdown
- handoff detail review with owner notes

V1 non-goals:
- staff workflows
- role management
- agent assignment systems
- full support-team inbox
- analytics productization

## Access Model

Control Room is accessed directly by the business owner.

Current assumptions:
- there is a single owner/operator
- staff logins and role design are deferred
- if the interface is kept internal or private, lightweight access controls are
  acceptable initially
- if exposed publicly on the internet, stronger authentication can be added
  later without changing the product model

## Data Boundaries

Avni distinguishes between operational logs and business records.

### Operational Logs

Operational logs exist for runtime health, debugging, alerts, and engineering
diagnostics.

Rules:
- no raw customer phone numbers
- no raw customer names unless explicitly justified
- no message body text
- use masked phone values when needed
- prefer internal IDs (`message_id`, `conversation_id`, `handoff_id`)
- include timings, status transitions, and error types

Example:
- `message_processed conversation_id=... message_id=... customer_phone=91987******10 total_ms=842`

### Business Records

Business records are the CRM system of record and retain full-fidelity data.

Examples:
- full phone number
- full conversation transcript
- handoff records
- timestamps
- customer metadata stored in the application database

These records may be:
- viewed in Control Room
- exported by the owner in CSV
- exported by the owner in Markdown

This means privacy-safe logging does not remove full business visibility. It
only prevents operational logs from becoming an uncontrolled copy of customer
data.

## Export Rules

Export support is part of the product, not a logging workaround.

Allowed export targets:
- conversations
- handoffs
- message activity summaries
- error and event summaries where appropriate

Export formats:
- CSV for structured business review and spreadsheet workflows
- Markdown for readable summaries, handoff review, and archival notes

Export expectations:
- exports are generated from application data stores, not scraped from logs
- exports should be explicit user actions
- exports should be auditable later if audit logging is added

## WhatsApp Policy Enforcement

Policy compliance is enforced in application code, not left to operator memory.

The send path must decide:
- whether a free-form message is allowed
- whether a template is required
- whether the message should be blocked and escalated instead

This policy layer should also become the natural place for:
- customer-service-window checks
- template gating
- pair-rate-limit handling
- outbound safety checks before send

## Queue and Failure Recovery

The current direction is a reliable-list queue design.

Chosen approach for now:
- keep Redis-based queueing
- move away from destructive pop-only semantics
- use an inbox plus processing-state pattern so work is recoverable after a
  worker crash

Why this was chosen:
- simpler migration path from the current implementation
- materially safer than the current `BLPOP` flow
- enough for the current phase

Future upgrade path:
- Redis Streams or a more advanced broker if queue visibility, replay, or
  multi-worker coordination needs grow

## Recommended V1 Metrics

System health:
- webhook health
- Redis health
- worker health
- database health
- WhatsApp send health
- Claude health
- Groq transcription health

Operational counters:
- messages received
- messages processed
- messages failed
- auto replies sent
- handoffs created
- queue depth
- average processing time

Owner-facing state:
- open conversations
- human-takeover conversations
- recent handoffs
- handoff notes and resolution state
- recent failures
- recent activity timeline

## Decision Summary

- Single-tenant per deployment is the current product truth.
- Avni Control Room is an owner-facing observability console, not a staff
  dashboard.
- Full business records remain viewable and exportable.
- Operational logs must remain privacy-safe and must not contain raw message
  text.
- Reliable-list queue semantics are the current failure-recovery choice.
- WhatsApp policy enforcement belongs in code.
