# Stagr Neutral Core — Overview

**Status:** Target design. What is built today is in
[ARCHITECTURE.md, section 8](../docs/ARCHITECTURE.md#8-status--roadmap).

**Scope:** Neutral core architecture for the Stagr toolkit.

**Audience:** Implementors, reviewers, future renderer authors.

---

## What Stagr is

Stagr is a **platform-neutral control plane** for SDLC pipelines. It translates a
declarative configuration file (`.agentic/config.yml`) into native CI/SCM wiring for
a target platform. Once rendered, the pipeline runs entirely inside the target platform.
The generated workflows run the **rules engine**, a file Stagr writes into the repository
(`06-runtime-boundary.md`). Stagr itself does not run during pipeline execution.

The three-layer model:

| Layer | Owner | When |
|---|---|---|
| **Contract / Policy** | Operator (config) | Authoring time |
| **Render** | Stagr CLI | `stagr apply` |
| **Execution** | CI platform, running the generated workflows and the embedded rules engine | Run time |

Stagr operates only at the **Render** layer. It writes the wiring; the platform runs
the work.

Which commands exist today is in [docs/CLI.md](../docs/CLI.md). The renderers return the
artifacts that `plan` lists and `apply` writes.

---

## Control plane litmus test

> "Does this require Stagr to be running while the pipeline executes?"

If yes, it belongs in the platform's generated artifacts, not in Stagr. Stagr must
never be a runtime dependency of the pipelines it generates. The rules engine passes this
test: it is one of the generated artifacts.

---

## Three-layer separation

```
Operator writes:        .agentic/config.yml
                              │
                    stagr apply (render time)
                              │
                              ▼
Stagr writes:         generated workflows + the rules engine file
                              │
                        CI platform
                              │
                              ▼
Platform executes:    change events → stage runs → one gate result
```

Each layer knows nothing about the layer above it at run time. The generated workflows
do not call back into Stagr.

---

## Scope of this specification

These documents specify the **neutral core**: the concepts, objects, and rules that are
platform- and provider-independent. The subject of governance is a change and its revision
(`02-canonical-stage-model.md`). They do not specify any particular renderer
implementation. Renderer implementations may add platform-specific details; they may
never contradict the neutral core.

### Documents in this set

| Document | Topic |
|---|---|
| `00-overview.md` | This file — scope and principles |
| `01-neutral-config-contract.md` | What belongs in `.agentic/config.yml` |
| `02-canonical-stage-model.md` | Change and revision, enumerations, NormalizedStage, profiles |
| `03-provider-backend-model.md` | Provider, backend, model separation; secret resolution |
| `04-render-time-architecture.md` | Render pipeline, object model, paths, artifact classes, invariants |
| `05-governance-and-trust.md` | TrustPolicy, RoutingPolicy, MergePolicy |
| `06-runtime-boundary.md` | The rules engine (eligibility, dependency rule, stage results, gate evaluation), EvidenceSpec, reconciliation, idempotency |
| `07-validation.md` | Static and environment validation checklists |
| `08-github-codex-mapping.md` | How the GitHub adapter and the Codex backend map the neutral model, and this repository's own hand-written workflows |
| `09-check-stages.md` | Build and other CI-result stages: executors, results, trust, ordering, work items |
| `doctor/` | Proposed design for `stagr doctor` (environment checks, roles, CI mode) |
