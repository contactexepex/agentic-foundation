# Roadmap & current state

Phased, honest, and tied to the charter. Each phase is control-plane work (declare / initialize /
govern / render / emit) — never runtime. Ordering follows the two locked decisions: **deepen
GitHub first**, and **name the agent-backend seam now, ship one GitHub-native backend**.

## Current state (what exists vs. what is new)

| Area | Today | This design adds |
|---|---|---|
| Dev-lane core | validate, review router, implement, Codex code + security review, thread cleanup, fail-closed gate, merge lanes — **rendered** | Formalizes the **ordered gate** (security/SAST before integration/perf/custom) and the readiness predicate |
| Trust/correctness | SHA-bound, fail-closed, base-controlled, serialized security review, scheduled sweep — **built** (PR #22/#25/#27) | States them as **invariants with required tests**; adds **anti-tamper via org rulesets** |
| Backends | `claude-code-action` (implement), `codex` (review/security) | Names the **agent-backend seam** (cloud/CLI as future adapters) |
| Governance | budgets/guardrails referenced in the contract | **Rendered** loop caps, cost ceiling, circuit breaker, and **escalation** terminal states |
| Audit | decision events in scope | First-class **decision record + provenance** stream and orchestrator seam |
| Onboarding | per-repo config; `doctor`/`plan`/`apply` on the roadmap | **Org-scoped** provisioning + **org-default/per-repo override** + **schema versioning/migration** |
| Platforms | GitHub renderer | Neutrality kept as a **contract principle**; more renderers later |

## Phase 1 — Harden the GitHub dev lane (now)

The demo-grade, provably-correct lane on GitHub.

- Lock the **ordered gate** and the readiness predicate ([dev-lane.md](dev-lane.md)).
- Elevate the **trust invariants** to tested guarantees; add **org-ruleset enforcement** so the
  gate cannot be edited away ([trust-and-correctness.md](trust-and-correctness.md)).
- Render **budgets, loop caps, and escalation** terminal states
  ([governance-and-limits.md](governance-and-limits.md)).
- Keep the **GitHub-native backends** (`claude-code-action`, `codex`); name the seam only.
- Emit a **minimal decision record** on gate outcomes and merge
  ([audit-and-provenance.md](audit-and-provenance.md)).

**Done when:** a trusted PR runs implement → review loop → security/SAST → tests → provably-ready,
human-approved merge, with every [edge-cases.md](edge-cases.md) row covered by a test.

### Phase-1 hardening backlog (surfaced by design review)

Specific **[target]** items the design docs reference — each is a gap between today's shipped
behaviour and the stated design:

- **Approved-story trigger.** Wire the `implement` stage to an approved-story **issue label** (today
  it is `workflow_dispatch` only). ([dev-lane.md](dev-lane.md))
- **Budget enforcement + finite default.** Budgets ship `enabled: false`; add loop-iteration caps, a
  cost ceiling, a circuit breaker, and a **finite default** so an unconfigured repo is never
  unbounded. ([governance-and-limits.md](governance-and-limits.md))
- **Implementer write isolation.** The Claude implementer job holds `contents`/`pull-requests: write`
  directly; move agent writes behind a buffered, separately-scoped apply step.
  ([security-and-secrets.md](security-and-secrets.md))
- **Exact-SHA review binding.** Drop the abbreviated-SHA **prefix** fallback in the review predicates
  in favour of the full machine-readable marker/object. ([trust-and-correctness.md](trust-and-correctness.md))
- **Auto-merge sweep ordering.** Add oldest-updated-first ordering to the merge sweep (the
  security-review sweep already has it). ([trust-and-correctness.md](trust-and-correctness.md))
- **Dismiss-stale-approvals invariant.** Make the ruleset setting a required onboarding invariant so
  human-lane re-approval on push is real. ([onboarding-and-config.md](onboarding-and-config.md))
- **Profile alignment.** Move `plan`/`docs` out of the shipped `full` profile to the sibling toolkits,
  and decide whether dev-lane `standard` makes `security` blocking. ([dev-lane.md](dev-lane.md))
- **Minimal commenting identity for review lanes.** Replace the broad remediation PAT
  (`CODEX_PAT`, Contents + PR R/W) used by the Codex review/security lanes with a narrowly-scoped
  commenting identity. ([security-and-secrets.md](security-and-secrets.md))
- **Shared review lock.** A cross-workflow lock (or single dispatch authority) for code vs. security
  review, closing the check-to-post window so "never concurrent" is guaranteed, not best-effort.
  ([trust-and-correctness.md](trust-and-correctness.md))
- **Decision-event emitter.** Build the audit/provenance emit layer — none ships today, so all of
  [audit-and-provenance.md](audit-and-provenance.md) is target.
- **Server-enforced `human-merge`.** Represent the `human-merge` hard stop as a server-enforced gate
  signal (e.g. a required status the label toggles) to close the label race branch protection cannot.
  ([trust-and-correctness.md](trust-and-correctness.md))
- **Automatic remediation loop.** A finding→remediation trigger (invoke the implementer on an open
  Codex finding / unresolved thread) with a bounded loop — today the fix push is external/manual.
  ([dev-lane.md](dev-lane.md))
- **Human-lane gate provisioning + verification.** Provision and verify the branch-protection ruleset
  (required checks + approvals) so the human lane's "no bypass" holds without relying on a
  separately-configured ruleset. ([governance-and-limits.md](governance-and-limits.md))
- **`doctor` environment probes.** Check that required secrets actually exist and the gate/ruleset is
  installed — today `doctor` only resolves config, lists secret names, and renders.
  ([onboarding-and-config.md](onboarding-and-config.md))

## Phase 2 — Org-scale onboarding & the stage catalogue

Make it a one-time, org-level setup and broaden the standard stages.

- **Org-scoped provisioning**: org app install, org secrets, org required/reusable workflows, org
  rulesets ([onboarding-and-config.md](onboarding-and-config.md)).
- **Org-default config + per-repo override**; `doctor --init` proposes/confirms. Includes a
  **live central-update path** (provisioning re-sync or an authenticated resolver), since `extends`
  is local-only today.
- **Auto-merge selectors** — contract fields to scope auto-merge by branch/label/author/condition
  (today only the toggle, method, protected paths, and required checks exist).
- **Schema versioning + migrations**.
- First-class **SAST/quality integrations** (Sonar, Checkmarx) and **integration / performance
  (as a `test`/`custom` stage) / custom** stages as reference templates.
- Fuller **provenance/attestation** stream for compliance (EU AI Act / ISO 42001 / SOC 2).

## Phase 3 — Backend & platform breadth

Prove neutrality where it pays.

- **Cloud-API backend** (provider cloud agents) behind the existing seam — a new adapter template
  **plus a `backend.name` enum addition** (backward-compatible), not a renderer rewrite; then a
  **CLI backend**.
- **Second platform renderer** (e.g. GitLab CI), then others — contract unchanged.
- **Hybrid** support: decouple "where code lives" (SCM) from "where agents run" (compute), for orgs
  whose runtime environment differs from their source host.
- **Autonomy window** as an opt-in extension of the auto-merge lane (time-boxed, fail-closed,
  fully recorded, `human-merge` still a hard stop).

## Explicitly out of scope (owned elsewhere)

- **Planning** (requirement → approved stories) — the service-shaped Planning sibling toolkit.
- **CD / deploy** — the renderer-shaped CD sibling toolkit.
- **Orchestration & monitoring** (what to start, fleet progress, the project brain) — the external
  orchestrator, which consumes stagr's events.
- **Agent runtime, model gateway, memory/RAG, hosted dashboard** — charter non-goals
  ([`../CHARTER.md`](../CHARTER.md) §5).

## Guardrail

Every item above must pass the charter litmus ([`../CHARTER.md`](../CHARTER.md) §4): *is this
WIRING/GOVERNANCE, or DOING-THE-WORK?* If an item cannot be reduced to declare / initialize /
govern / render / emit, it belongs in a backend, a sibling toolkit, or the user's CI — not in
stagr.
