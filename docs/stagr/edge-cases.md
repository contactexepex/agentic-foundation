# Edge-case catalogue — negative → positive behaviour

This is the behaviour contract for **every** situation the dev lane can hit, from fully broken to
fully green. The rule throughout: **fail-closed and escalate; never open the merge on doubt, never
loop forever, never stall silently.** Each row should have a corresponding test (static, or a
behavioural fixture with a stubbed platform API).

## Legend

- **Blocked** = merge is not possible; PR is not ready.
- **Escalate** = stop automation, apply `human-merge`, notify, record a decision event.
- **Ready** = all gate predicates pass; PR awaits human approval (or auto-merge if the module is
  on).

## 1. Eligibility

| Case | Behaviour |
|---|---|
| Fork PR | Drives no automation; no credential; **Blocked** for auto actions |
| Draft PR | **Blocked** until marked ready |
| Base is not the default branch | **Blocked** (out of the gate's scope) |
| Untrusted author | Automation does not run; **Blocked** |
| `human-merge` label present | Hard stop for the **auto-merge lane** only; does **not** block human-lane readiness (a human may still merge) |
| PR changes a `merge.protected_paths` file (default `.github/workflows/**`, `.agentic/**`) | **Control-plane guard**: left for a human — never auto-merged |
| Merge conflict (`mergeable=false`) | **Blocked** (fail-closed) |
| Behind / not clean (`mergeable_state != clean`: behind, blocked, unstable, dirty) | **Blocked** |
| Mergeability still computing (`mergeable=null`) | **Blocked** (fail-closed until GitHub reports `true`) |
| PR already merged/closed | No-op |

## 2. Implementation & the review loop

| Case | Behaviour |
|---|---|
| Implement produces no PR | Nothing to gate; story stays open; escalate on repeated failure |
| Code review posts findings | Implementer fixes; new commits **re-trigger** review on the new head |
| New push mid-review | Review re-runs on the latest head; old-head results do not count |
| Findings persist after the iteration cap | **Escalate** (stop looping) |
| Fix reintroduces a prior finding (oscillation) | Circuit breaker trips → **Escalate** |
| Review never returns / backend error | Fail-closed **Blocked**; retry within cap; then **Escalate** |
| Code + security review would run concurrently | Security is **deferred** until code review converges (never concurrent) |

## 3. Checks, statuses, and reruns

| Case | Behaviour |
|---|---|
| Combined status not `success` | **Blocked** |
| A required check missing / pending / `action_required` | **Blocked** (fail-closed) |
| A check `cancelled`/`stale` with no newer success | **Blocked** |
| A check flapped `success`→`queued`/`cancelled` | Latest-by-id wins → **Blocked** (no fallback to old success) |
| Old-head success, new head has no result | **Blocked** (SHA-bound) |
| Same-named check from the **wrong app** | Not matched (name+app-id identity) → requirement unmet → **Blocked** |
| PR deletes/renames `validate.yml` so no failing check exists | Trusted workflow-run check for the head is absent → **Blocked** |
| Unrelated failing check-run not in the configured list | The gate's **separate check-run scan** catches it → **Blocked** (the combined commit status does **not** include Checks-API runs, so the check-run scan is what covers this; the list is not an allowlist) |
| Integration/perf/custom stage red | **Blocked** |
| A stage hangs past its timeout | Times out → its check not green → **Blocked** → **Escalate** |

## 4. Reviews, threads, approvals

| Case | Behaviour |
|---|---|
| Open (unresolved) review thread | **Blocked** until zero open threads on the head |
| Reviewer requested changes | **Blocked** until superseded by a newer decisive review |
| Code review bound to an old head only | Does not satisfy the head-bound requirement → **Blocked** |
| Security review missing or old-head | **Blocked** (both reviews must be head-bound + complete) |
| Security summary row edited/deleted/ambiguous | Fail-closed **Blocked** |
| Human approves, then a new commit is pushed | Re-approval is required **only if** the repo's ruleset enables **dismiss-stale-approvals** (an onboarding invariant — see [onboarding-and-config.md](onboarding-and-config.md)); GitHub does not invalidate an approval on push by itself |
| Thread resolved but no webhook fired | The **scheduled sweep** catches it and re-evaluates |

## 5. Forgery / tamper attempts

| Case | Behaviour |
|---|---|
| Forged/`statuses:write` router description claims "passed" | Description is informational only; gate re-derives from first-class signals → not waived |
| PR content tries to run in the gate | Gate never checks out/executes PR content (`pull_request_target`, no head checkout) |
| Malicious workflow added by the PR | Gate definition/token come from base; PR-added workflow cannot grant merge |
| Attempt to reach a credential from an untrusted stage | Principal isolation + least privilege → no access |
| Sentinel injected into PR title/body/branch/author | Must never reach the build/publish step or a credential (data-flow test) |

## 6. Budgets & limits — **[target]** (budgets ship `enabled: false`; not enforced today)

| Case | Behaviour **[target]** |
|---|---|
| Review-iteration cap reached | Stop → **Escalate** |
| Cost ceiling exceeded | Stop spending → **Escalate** with partial state recorded |
| No budget configured | Safe finite default applies (never "unlimited") |

## 7. Races & concurrency

| Case | Behaviour |
|---|---|
| State changes between last read and merge | Re-read + re-check mutable predicates + head-move check before the SHA-pinned merge. SHA-pinning prevents merging a *different* commit, but the predicates are **not atomic**: a `human-merge` add / thread reopen / review turning blocking on the **same** SHA can admit a now-unready commit. Only **server-side branch protection** closes these atomically (see [trust-and-correctness.md](trust-and-correctness.md)) |
| Event run and scheduled sweep overlap on one PR | **Not** globally serialized (per-PR group for events, separate group for the sweep); safeguards are **idempotent re-evaluation**, the final re-read + head-move check, and the gate's own in-progress check-run making an event run **defer** so a later sweep completes |
| Two events for the same PR | Idempotent; duplicate/echo events are skipped |
| A signal has no webhook at all | The scheduled sweep is the backstop |

## 8. Config & platform

| Case | Behaviour |
|---|---|
| Invalid config | `validate_config()` fails at render time (schema → coherence → templating safety) — never renders a broken/unsafe workflow |
| `${{ }}` injected into an operator-controlled field | Templating-safety validator rejects it |
| Config targets an unsupported schema version | Rejected with a migration message (`doctor`) |
| Required secret absent (by name) | `doctor` reports it; the model-consuming stage fails loud rather than guessing |
| Unresolved model on a model-consuming backend | Fail loud; never guess a version (Codex supplies its own model, so the rule does not apply to it) |

## 9. Fully positive path

| Case | Behaviour |
|---|---|
| Trusted same-repo PR; CI green; code review converged & clean; security + SAST clean; integration/perf/custom green; zero open threads; no changes requested — all on the current head | **Ready** → human approves and merges (or `auto_merge` module merges) → merge event + decision record emitted → CD/orchestrator pick it up |

## Test-coverage rule

For each row above there must be a static assertion or a behavioural fixture (stubbed platform
API) proving the stated behaviour. A row without a test is an **open gap**, and stagr's definition
of done ([`../../CLAUDE.md`](../../CLAUDE.md)) is not met until it is covered.
