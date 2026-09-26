# The development lane and the merge gate

This is stagr's heart: the ordered stage graph from an approved story to a merged PR, and the
gate that decides when the PR is **provably ready**.

> **Shipped vs. target for this lane (read first).** What renders today is narrower than the full
> flow below:
> - **implement** is triggered by `workflow_dispatch` only; the **review→fix loop is not
>   auto-driven** — after a finding, an **external actor** (a human, or an orchestrator) pushes the
>   fix, and the review lane only *re-requests* Codex on the new commit. An automatic
>   finding→remediation trigger with a bounded loop is **[target]**.
> - **code review** does **not** re-run on every push under the shipped default: `routing.fast_path`
>   defaults **on**, so the router can classify a trivial head and **skip** the review. (This repo
>   disables fast-path, so every PR is reviewed; that is a config choice, not the default.)
> - **SAST/quality, integration-test, performance, custom** stages are **[target]** — no workflow
>   renders them today, and the auto-merge gate *rejects* a blocking `test`/`integration-test` stage
>   (it renders no merge signal). Their rows and ordering below describe the intended graph.
> - **security review** "never concurrent" is **best-effort** (separate concurrency groups leave a
>   residual window — see [trust-and-correctness.md](trust-and-correctness.md)).
> - the **human-lane merge gate is not rendered by stagr** — it depends on an externally-enforced
>   ruleset ([governance-and-limits.md](governance-and-limits.md), [onboarding-and-config.md](onboarding-and-config.md)).

## The flow

```
approved story issue
      │  (trigger: workflow_dispatch [shipped]; approved-story label [target])
      ▼
[implement]  Claude opens a PR
      │  (trigger: PR opened/updated)
      ▼
[code-review]  Codex reviews ──► fix pushed by an external actor ──► new commit re-triggers review
      │        (loop until ZERO open review threads; the fix push is NOT auto-driven today — see note)
      ▼  (only after code review has converged: completed + clean on head)
[security-review]  Codex security review  ── runs ONCE, never concurrent with code review
      +  [sast/quality integrations]  Sonar / Checkmarx (if configured) ── must be clean
      │  (all security findings addressed, zero open security comments)
      ▼
[integration-test] → [performance-test] → [custom …]   (if configured)
      │  (each a required check, all green)
      ▼
MERGE GATE  ── no open comments AND every configured check green AND both reviews head-bound
      │
      ▼
ready for human approval ──► human merges         (default)
                        └─► auto_merge module merges  (opt-in only)
```

Running underneath the whole lane is **validate/CI** — `build.commands` (build + unit tests) —
which defines "green" for the repo and is itself a blocking check.

## Stage-by-stage

| Stage | Trigger | Gate | Loop / ordering rule |
|---|---|---|---|
| **implement** | manual `workflow_dispatch` **[shipped]**; approved-story **issue label** **[target]** | n/a (produces the PR) | one PR per story |
| **validate / CI** | PR opened/updated, push | blocking | build + unit tests must pass on the head |
| **code-review** (Codex) | PR opened/updated (`synchronize`) | advisory or blocking | re-runs on each push **unless fast-path skips a trivial head** (shipped default `fast_path: on`); converges only when **zero open review threads** on the current head |
| **security-review** (Codex) | code review completed + clean on head | blocking **when configured** (advisory in the shipped `standard` profile) | **runs once, after** code review converges; **never concurrent** (best-effort). With auto-merge on **and an advisory security stage**, the gate may merge after code review **without** a blocking security review — see [trust-and-correctness.md](trust-and-correctness.md) |
| **sast / quality** (Sonar, Checkmarx) **[target]** | PR opened/updated | blocking (if configured) | grouped with security; clean **before** integration/perf/custom — *not rendered today* |
| **integration-test** **[target]** | after security clean (or as configured) | blocking (if configured) | default: **after** the security group — *not rendered; auto-merge rejects a blocking one* |
| **performance-test** (a `test`/`custom` stage) **[target]** | after integration (or as configured) | blocking (if configured) | default: after integration — *not rendered today* |
| **custom** **[target]** | as configured (`depends_on`) | advisory or blocking | placed anywhere via `depends_on` — *not rendered today* |

### Why security runs before integration/performance by default

Vulnerable code should not consume integration or performance budget, and a merge should never
happen with an open security finding. So the **security + SAST group gates ahead of** the
integration/performance/custom stages **by default**. This ordering is **configurable via
`depends_on`** — a repo that wants integration tests in parallel with security can express that —
but the default keeps the expensive and the risky stages behind the cheap security gate.

### Why security review is sequenced after code review

The Codex backend errors if a code review and a security review run **concurrently** on the same
PR. So the security review is triggered **only after** the code-review loop has converged
(completed and clean on the exact head). This is a correctness constraint, not a preference — see
[trust-and-correctness.md](trust-and-correctness.md#sequencing-code-vs-security-review).

## The merge gate — the definition of "provably ready"

A PR is **ready** only when **all** of the following hold on the **exact current head SHA**
(every check is fail-closed — missing/pending/unknown ⇒ not ready). All are **[shipped]** in the
auto-merge gate unless marked:

1. **Eligible** — open, not draft, not a fork, base is the default branch, trusted author, and
   GitHub reports `mergeable == true` and `mergeable_state == clean` (no conflict, not behind,
   not still computing).
2. **CI green** — the combined commit status is `success`, **and** every latest check-run on the
   head is **terminal with an accepted conclusion**. The gate **scans check-runs separately** (the
   combined status omits Checks-API runs), selecting the **latest attempt by id** per `(app.id, name)`.
   The **general** scan accepts `success`, **`neutral`, or `skipped`**; the **mandatory `validate`
   check and any operator-listed required checks must be exact `success`** — `validate` both as a
   completed-success check from the `github-actions` app **and** backed by a trusted `validate.yml`
   workflow run for this exact head.
3. **Every configured check green** — each required check-run/status is a clean success on the head
   (SAST/quality, integration, test, custom). The configured list is **not** an allowlist that
   hides an unrelated failing check-run (that is caught by #2).
4. **Code review complete — when required** — if a blocking Codex **code** review is configured
   (`require_codex_code_review`), a head-bound Codex code review has completed and is clean. A profile
   with no blocking code review (e.g. `minimal`, or a `custom` graph without one) does not require it.
5. **Security review complete — when required** — if a blocking Codex **security** review is
   configured (`require_codex_security_review`), a head-bound Codex security review has completed and
   is clean. Not required when no blocking security stage is configured.
6. **Zero open review threads** — no unresolved review threads, from **any** stage (see the advisory
   note in [concepts.md](concepts.md#trigger--gate--the-whole-stage-contract)).
7. **No changes requested** — no reviewer's latest decisive review is `CHANGES_REQUESTED`.

**Human lane vs. auto-merge.** A PR satisfying 1–7 is **ready for human approval**, and a human may
merge it. The **`human-merge` label does not block human-lane readiness** — it is a **hard stop for
the auto-merge lane only**. So *auto-merge* eligibility = 1–7 **plus** the absence of `human-merge`
**plus** the **control-plane guard** (no changed file matches `merge.protected_paths` — default
`.github/workflows/**` and `.agentic/**`; a PR touching one is left for a human) **plus** the team's
auto-merge configuration ([governance-and-limits.md](governance-and-limits.md)).
The **how** (SHA binding, no forgeable signals, base-controlled definitions, and the residual
last-read race) is in [trust-and-correctness.md](trust-and-correctness.md).

## Profiles

A profile expands to a default dev-lane graph; explicit stages merge onto it (same id overrides).

The **shipped** expansions today (id — gate):

| Profile | Stages **[shipped]** |
|---|---|
| `minimal` | implement (advisory), review (advisory) |
| `standard` | implement, review (**blocking**), security (advisory) |
| `full` | implement, security (**blocking**), test (**blocking**), integration-test (**blocking**), review (**blocking**) |
| `custom` | none — every stage is declared |

> **Scope note.** `plan` and `docs` are **not** dev-lane stages — under the refined dev-lane scope
> they move to the **Planning** and **CD** sibling toolkits
> ([overview.md](overview.md#scope-alignment-with-older-docs)), so no stagr profile emits them. The
> stage **types** stay valid in the contract, so a repo can still declare them explicitly.
>
> **[target] migration.** One gap between the shipped profiles and this design is tracked in
> [roadmap.md](roadmap.md), not silently assumed here:
> 1. `standard`'s `security` stage is **advisory** today; whether the dev-lane default should make it
>    blocking is a roadmap decision, not a claim of current behaviour.

## Handoffs (the GitHub-artifact seams)

- **In:** the Planning toolkit creates an **approved story issue** (with dependency metadata).
  Today the `implement` stage is started by `workflow_dispatch` **[shipped]**; consuming the story
  **issue label** directly is **[target]** ([roadmap.md](roadmap.md)). Either way, stagr does not
  decide *which* story is ready — that ordering is the orchestrator's (see
  [audit-and-provenance.md](audit-and-provenance.md)).
- **Out:** on merge, stagr emits a **merge event + decision record**; the CD toolkit and the
  orchestrator consume it. stagr's responsibility ends at the merged PR.
