# Roadmap & current state

Phased, honest, and tied to the charter. Each phase is control-plane work (declare / initialize /
govern / render / emit) — never runtime. Ordering follows the two locked decisions: **deepen
GitHub first**, and **name the agent-backend seam now, ship one GitHub-native backend**.

## Current state (what exists vs. what is new)

| Area | Today | This design adds |
|---|---|---|
| Dev-lane core | Stagr renders a workflow per Codex `review`/`security` stage, a routing workflow, and a governance (merge-gate) workflow. This repository's hand-written workflows also run validate, thread cleanup, and the foundation auto-merge gate | Formalizes the **ordered gate** (security/SAST before integration/perf/custom) and the readiness predicate |
| Trust/correctness | SHA-bound, fail-closed, base-controlled, scheduled sweep — **built** in this repository's hand-written gate (PR #22/#25/#27). Security review is serialized **within its own workflow** (residual cross-workflow window — see trust doc) | States them as **invariants with required tests**; adds **anti-tamper via org rulesets**; closes the review window + base-retarget binding |
| Backends | `codex` (review/security) is the only backend renderer and renders on GitHub | Names the **agent-backend seam** (cloud/CLI as future adapters) |
| Governance | no budget or guardrail keys in the contract | **[target]** loop caps, cost ceiling, circuit breaker, and **escalation** terminal states — not yet rendered |
| Audit | decision events **in scope but not emitted** (no emitter ships) | First-class **decision record + provenance** stream and orchestrator seam — all **[target]** |
| Onboarding | per-repo config written by hand; the CLI offers `help`, `plan` and `apply` — `init` and `doctor` (#203) are planned | **Org-scoped** provisioning + **org-default/per-repo override** |
| Platforms | GitHub renderer | Neutrality kept as a **contract principle**; more renderers later |

## Phase 1 — Harden the GitHub dev lane (now)

The demo-grade, provably-correct lane on GitHub.

- Lock the **ordered gate** and the readiness predicate ([dev-lane.md](dev-lane.md)).
- Elevate the **trust invariants** to tested guarantees; add **org-ruleset enforcement** so the
  gate cannot be edited away ([trust-and-correctness.md](trust-and-correctness.md)).
- Render **budgets, loop caps, and escalation** terminal states
  ([governance-and-limits.md](governance-and-limits.md)).
- Keep the **GitHub-native backend** (`codex`); name the seam only.
- Emit a **minimal decision record** on gate outcomes and merge
  ([audit-and-provenance.md](audit-and-provenance.md)).

**Done when:** a trusted PR runs review loop → security/SAST → tests → provably-ready,
human-approved merge, with every [edge-cases.md](edge-cases.md) row covered by a test.

### Phase-1 hardening backlog (surfaced by design review)

Specific **[target]** items the design docs reference — each is a gap between today's shipped
behaviour and the stated design:

- **Budget enforcement + finite default.** There are no budget keys today; add loop-iteration caps, a
  cost ceiling, a circuit breaker, and a **finite default** so an unconfigured repo is never
  unbounded. ([governance-and-limits.md](governance-and-limits.md))
- **Exact-SHA review binding.** Drop the abbreviated-SHA **prefix** fallback in the review predicates
  in favour of the full machine-readable marker/object. ([trust-and-correctness.md](trust-and-correctness.md))
- **Auto-merge sweep ordering.** Add oldest-updated-first ordering to the merge sweep (the
  security-review sweep already has it). ([trust-and-correctness.md](trust-and-correctness.md))
- **Dismiss-stale-approvals invariant.** Make the ruleset setting a required onboarding invariant so
  human-lane re-approval on push is real. ([onboarding-and-config.md](onboarding-and-config.md))
- **Minimal commenting identity for the security-review lane.** Replace the broad remediation PAT
  (`REMEDIATION_TOKEN`, Contents + PR R/W) used by the Codex security-review lane with a narrowly-scoped
  commenting identity. ([security-and-secrets.md](security-and-secrets.md))
- **Single review dispatch.** One authority that starts both the code and the security review (today
  the Codex App starts the code review by itself), so "never concurrent" is guaranteed, not
  best-effort.
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
- **`doctor` environment probes.** When `stagr doctor` is built (issue #203), have it check that
  required secrets actually exist and the gate/ruleset is installed, beyond resolving config and
  listing secret names.
  ([onboarding-and-config.md](onboarding-and-config.md))
- **Base-retarget evidence binding.** Invalidate/rerun validate + review when a PR is retargeted to a
  new base (evidence is head-SHA-bound only today). ([trust-and-correctness.md](trust-and-correctness.md))
- **Fork build-token hardening.** Prevent a fork PR's build commands from reading even the
  read-scoped `GITHUB_TOKEN` in Validate. ([security-and-secrets.md](security-and-secrets.md))
- **Durable audit outbox.** A durable outbox / sink delivery-acknowledgement so a decision record
  cannot be lost to run-log retention. ([audit-and-provenance.md](audit-and-provenance.md))

## Phase 2 — Org-scale onboarding & the stage catalogue

Make it a one-time, org-level setup and broaden the standard stages.

- **Org-scoped provisioning**: org app install, org secrets, org required/reusable workflows, org
  rulesets ([onboarding-and-config.md](onboarding-and-config.md)).
- **Org-default config + per-repo override**; `stagr init` proposes/confirms. Includes a
  **live central-update path** (provisioning re-sync or an authenticated resolver), since there is
  no config layering today.
- **Auto-merge lane and selectors** — contract fields to turn auto-merge on and scope it by
  branch/label/author/condition (the contract has no auto-merge keys today).
- First-class **SAST/quality integrations** (Sonar, Checkmarx) and **integration / performance
  (as a `test`/`custom` stage) / custom** stages as reference templates.
- Fuller **provenance/attestation** stream for compliance (EU AI Act / ISO 42001 / SOC 2).

## Phase 3 — Backend & platform breadth

Prove neutrality where it pays.

- **Cloud-API backend** (provider cloud agents) behind the existing seam — one new backend
  renderer registered in the core, not a renderer rewrite; then a **CLI backend**.
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
