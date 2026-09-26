# Audit & provenance — decision events and the orchestrator seam

Emitting run/cost/decision events is explicitly **in scope** for the control plane
([`../CHARTER.md`](../CHARTER.md) §2). This page defines what stagr emits, why it is both the clean
seam to an external orchestrator **and** the compliance/provenance wedge, and where the line to
"not a dashboard" sits.

> **Status: [target].** No decision-event emitter ships in `stagr/` today — this entire page is
> **design intent**, not current behaviour. The decision records, provenance fields, delivery
> retries, and sink-failure handling below describe what the emit layer will do; they are tracked in
> [roadmap.md](roadmap.md). Do not read any statement here as an existing guarantee.

## stagr emits; it does not store or display

stagr is not a database or a UI. It **emits a structured event stream** to the org's existing
tools (log/observability sink, event bus, or an orchestrator's ingest). Holding history,
correlating across PRs, and drawing dashboards are consumers' jobs — not stagr's
([overview.md](overview.md#non-goals-what-keeps-stagr-a-tool-not-a-framework)).

## The decision record

Every consequential gate action emits a **decision record** — a structured, append-only event.
Minimum fields:

- **what** — the stage/gate and the decision (`review-converged`, `security-clean`,
  `blocked:<reason>`, `escalated:<reason>`, `ready`, `merged`).
- **which head** — the exact commit SHA the decision was bound to.
- **which agent/model/backend** — the principal and model that produced the artifact.
- **which policy** — the config/schema version and the specific rule that applied.
- **who** — the acting principal (and, for a merge, the approver in the human lane).
- **when** — timestamp and correlation id (PR + story).

Records are **tamper-evident** (append-only, ordered, ideally signed) and **secret-free** (values
redacted per [security-and-secrets.md](security-and-secrets.md)).

## Two jobs, one stream

1. **Seam to the orchestrator.** The external orchestrator (which decides *what* to start and
   tracks live progress) consumes these events — most importantly the **merge event**, which lets
   it update the project brain and unblock dependent stories. stagr and the orchestrator
   communicate **only through GitHub artifacts + this event stream**, never by calling each other
   ([overview.md](overview.md#the-two-sibling-toolkits)).

2. **Compliance & provenance wedge.** The same stream is a per-change **provenance trail**: which
   agent wrote what, under which policy version, reviewed by whom, gated how, approved by whom. That
   is exactly what regulated orgs need for AI-generated-code governance (EU AI Act, ISO 42001,
   SOC 2) — and it is a position the platform incumbents structurally under-serve. Provenance is a
   named pillar, not plumbing.

## Cost & run telemetry

Alongside decisions, stagr emits **run and cost events** (per stage: tokens/cost, duration,
outcome) so budgets ([governance-and-limits.md](governance-and-limits.md)) are auditable and an
orchestrator can see which lane is expensive or stuck. Telemetry is an **emit-adapter**: nothing
about the sink, endpoint, or format is hardcoded; it adapts to what the org already runs.

## Boundary: emit-adapter, not observability platform

- stagr **emits** to a configured sink; it does not host storage, search, or a UI.
- It does not reinvent LLM/agent observability — it speaks a standard event shape (e.g.
  OpenTelemetry GenAI conventions) so an existing backend ingests it.

### The record must always exist (sink failure handling)

Because "every decision is recorded" and "a merge without a record is defective" must both hold, the
**platform's native run log is the durable record of record**, written **first and locally**; remote
emission to a configured sink is **best-effort on top**. Therefore:

- **No sink configured** → the record lives in the native run log; nothing is lost.
- **Configured sink unavailable** (webhook down, OTLP collector unreachable, bus rejects) → the
  durable run-log record is already written, so the merge is **not blocked** by a remote outage; the
  failed delivery is **flagged and retried** (best-effort), never silently dropped.
- The merge is **never** gated on a remote sink's availability — only on the local record existing.
  This keeps "a merge always has a record" true without letting an external outage stall the gate.

## What "auditable" means here

Auditable means: **every** gate decision and escalation produces a record; each record is
SHA-bound, policy-versioned, principal-attributed, and secret-free; and the merge event carries
enough for a consumer to both continue the pipeline and reconstruct *why this change was allowed
in*. A merge with no decision record is a defect.
