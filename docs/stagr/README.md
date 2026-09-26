# stagr — design & roadmap

This folder is the **authoritative design and roadmap for stagr** (the agentic-foundation
toolkit). It is deliberately split into small, single-purpose files so each can be reviewed
on its own, with less room for error than one large document.

For the layered architecture (contract → provider adapters → backends → platform renderers →
CLI), see [`../ARCHITECTURE.md`](../ARCHITECTURE.md). For the scope guardrail, see
[`../CHARTER.md`](../CHARTER.md). This set **refines and extends** those; where a scope
statement here differs from an older doc, the note in [`overview.md`](overview.md#scope-alignment-with-older-docs)
explains the reconciliation.

## Read in this order

| # | Doc | What it answers |
|---|---|---|
| 1 | [overview.md](overview.md) | What stagr is, its bounded scope, non-goals, and the two sibling toolkits (planning, CD). |
| 2 | [concepts.md](concepts.md) | The vocabulary: stage, trigger, gate, backend + the agent-backend seam, merge lanes. |
| 3 | [dev-lane.md](dev-lane.md) | The dev-lane stage graph and the ordered merge gate — stagr's heart. |
| 4 | [trust-and-correctness.md](trust-and-correctness.md) | Why the gate cannot be tricked or bypassed (fail-closed, SHA-bound, anti-tamper). |
| 5 | [governance-and-limits.md](governance-and-limits.md) | Budgets, loop caps, escalation, and the human-approval / auto-merge lanes. |
| 6 | [security-and-secrets.md](security-and-secrets.md) | Per-stage least privilege, principal isolation, and the secret model. |
| 7 | [audit-and-provenance.md](audit-and-provenance.md) | Decision events, provenance/attestation, and the seam to an external orchestrator. |
| 8 | [onboarding-and-config.md](onboarding-and-config.md) | Org-scoped onboarding, org-default + per-repo override, and config versioning. |
| 9 | [edge-cases.md](edge-cases.md) | The negative→positive behaviour catalogue: what stagr does in every failure mode. |
| 10 | [roadmap.md](roadmap.md) | Phased roadmap and the honest current-state map. |

## Design rules these docs follow

- **stagr declares, initializes, and governs — it never executes.** (Charter §2.)
- **Fail-closed everywhere:** any missing, unknown, or errored signal blocks the merge; it
  never opens it.
- **Platform-neutral by contract, GitHub-first by delivery.** The contract names no CI system;
  today only the GitHub renderer ships.
- **Minimal by default, curated when advanced.** The common repo is a handful of config lines.
