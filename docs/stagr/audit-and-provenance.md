# Audit & provenance — decision events

Emitting run, cost and decision events is in scope for the control plane
([`../CHARTER.md`](../CHARTER.md) §2). This page defines what stagr should emit, why the same stream
serves both other tools and compliance, and where the line to "not a dashboard" sits.

> **Status: design only.** No decision-event emitter exists in `stagr/`, so nothing on this page is
> built. The work is tracked in issues #66 (sink configuration), #74 (minimal decision record),
> #76 (run and cost events), #78 (durable outbox), #80 (provenance fields), #82 (a record for every
> gate decision), #114 (attestation stream) and #127 (compliance mapping).

## stagr emits; it does not store or display

stagr is not a database or a UI. It **emits a structured event stream** to the org's existing tools
(a log or observability sink, an event bus, or another tool's ingest). Keeping history, correlating
across pull requests and drawing dashboards are the consumers' jobs, not stagr's
([`../CHARTER.md`](../CHARTER.md) §5).

## The decision record

Every consequential gate action emits a **decision record**: a structured, append-only event. The
minimum fields are:

- **what**: the stage or gate and the decision (for example `ready`, `blocked:<reason>`, `merged`).
- **which head**: the exact commit SHA the decision was bound to.
- **which agent, model and backend**: the principal and model that produced the artifact.
- **which policy**: the config and schema version and the specific rule that applied.
- **who**: the acting principal (and, for a human-gated merge, the approver).
- **when**: a timestamp and a correlation id (pull request and story).

Records are **tamper-evident** (append-only, ordered, ideally signed) and **secret-free** (values
are never written, see [security-and-secrets.md](security-and-secrets.md)).

## Two jobs, one stream

1. **Feed to other tools.** Anything that needs to know what happened, such as an external
   orchestrator deciding what to start next or a deploy toolkit reacting to a merge, consumes these
   events, most importantly the **merge event**, instead of polling the repository. stagr and those
   tools do not call each other.

2. **Compliance and provenance.** The same stream is a per-change **provenance trail**: which agent
   wrote what, under which policy version, reviewed by whom, gated how, approved by whom. That is
   what regulated organizations need for AI-generated-code governance (EU AI Act, ISO 42001,
   SOC 2). Provenance is a named pillar, not plumbing.

## Cost and run telemetry

Alongside decisions, stagr emits **run and cost events** per stage (tokens or cost, duration,
outcome), so spending is auditable and another tool can see which stage is expensive or stuck.
Telemetry is an **emit adapter**: nothing about the sink, endpoint or format is hardcoded, so it
adapts to what the org already runs.

## Boundary: emit adapter, not observability platform

- stagr **emits** to a configured sink. It does not host storage, search or a UI.
- It does not reinvent LLM or agent observability. It uses a standard event shape (for example
  OpenTelemetry GenAI conventions) so an existing backend can ingest it.

### The record must always exist (sink failure handling)

"Every decision is recorded" and "a merge without a record is a defect" must both hold. A platform's
own run log is **not** enough for that: it is retention-bound and can be deleted. So the design
writes every record to a **durable outbox** first and treats delivery to a remote sink as
best-effort on top:

- **No sink configured**: the record is still committed to the durable outbox.
- **Sink unavailable** (webhook down, collector unreachable, bus rejects): the record is already in
  the outbox, so the merge is **not blocked** by a remote outage. Delivery is **retried from the
  outbox** and never silently dropped.
- The merge waits for the **outbox commit**, not for any remote sink.

## What "auditable" means here

Auditable means: **every** gate decision produces a record; each record is bound to a commit,
versioned by policy, attributed to a principal and free of secrets; and the merge event carries
enough for a consumer to both continue its work and reconstruct *why this change was allowed in*.
A merge with no decision record is a defect.
