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

## Phase 2 — Org-scale onboarding & the stage catalogue

Make it a one-time, org-level setup and broaden the standard stages.

- **Org-scoped provisioning**: org app install, org secrets, org required/reusable workflows, org
  rulesets ([onboarding-and-config.md](onboarding-and-config.md)).
- **Org-default config + per-repo override**; `doctor --init` proposes/confirms.
- **Schema versioning + migrations**.
- First-class **SAST/quality integrations** (Sonar, Checkmarx) and **integration/performance/custom**
  stages as reference templates.
- Fuller **provenance/attestation** stream for compliance (EU AI Act / ISO 42001 / SOC 2).

## Phase 3 — Backend & platform breadth

Prove neutrality where it pays.

- **Cloud-API backend** (provider cloud agents) behind the existing seam — a new adapter, not a
  rewrite; then a **CLI backend**.
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
