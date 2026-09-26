# Trust & correctness — why the gate cannot be tricked or bypassed

The gate is stagr's product. If it can be fooled into merging unready code, nothing else matters.
This page is the threat model and the invariants that make the gate sound. Every rule is
**statically or behaviourally tested** against the rendered workflow (see
[roadmap.md](roadmap.md) — the renderer's own test strategy).

## The adversary

Per [`../../AGENTS.md`](../../AGENTS.md), all PR/issue/comment content is **untrusted data**. The gate
must stay correct when a PR author (or any actor who can comment, push, or install an app) tries
to:

- forge a "passing" signal, edit a review summary, or delete/rename a workflow so no failing check
  exists;
- race a status change between the last read and the merge;
- open the merge with a stale success from an older commit;
- reach a credential or a stage the actor should never touch.

## Non-negotiable invariants

1. **Fail-closed, always.** Any signal that is missing, pending, unknown, malformed, or errored
   ⇒ **not ready**. The gate only ever opens on an explicit, current, clean success. There is no
   "assume green."

2. **SHA-bound.** Every predicate is evaluated on the **exact current head SHA**. A success, a
   review, or a status bound to any other commit does not count. The merge call itself is
   SHA-pinned, so the gate can never merge a *different* commit than the one it verified.

3. **Base-controlled definition and execution.** The gate workflow's definition **and** its token
   come from the trusted base branch, never from PR content. The gate **never checks out or
   executes PR code**, and invokes no repository-sourced script/action over PR content. On GitHub
   this is `pull_request_target` with no checkout of the head.

4. **No forgeable signal.** A signal any `statuses: write` actor could write is **never** trusted
   to *waive* a requirement. A router/aggregate status's *description* is informational only; the
   gate re-derives readiness from first-class, identity-checked signals.

5. **Positive check identity.** A required external check matches by **name AND app id** (not name
   alone), so a same-named check from the wrong app cannot spoof it. The mandatory `validate`
   requires both a completed successful check from the trusted app **and** a trusted workflow run
   of the `validate` path for the exact head — closing the "delete/rename validate.yml so no
   failed check exists" hole.

6. **Deterministic rerun rule.** Among attempts matching an identity, the gate selects the
   **latest by check-run id** (monotonic; timestamps only corroborate). That latest attempt must
   be completed with an accepted conclusion. It **never** falls back to an older success when a
   newer attempt exists (no success→queued/cancelled/stale downgrade slips through).

7. **Re-read before merge.** After all predicates pass, the gate **re-reads fresh authoritative
   state and re-checks the mutable predicates** as the final step before the SHA-pinned merge. The
   residual last-read→merge race is documented honestly; the SHA-pin guarantees it can never merge
   the wrong commit, and the scheduled sweep bounds worst-case latency.

## Sequencing code vs. security review

The Codex backend **errors if a code review and a security review run concurrently** on one PR.
Therefore:

- the **code-review loop runs per push** until it converges (completed + clean on the head);
- the **single security review** is triggered **only after** convergence;
- the two are **globally serialized** so an event-driven run and a scheduled sweep cannot start a
  second review while one is in flight.

This is why the gate requires a head-bound code review **and** a head-bound security review to have
completed — a security review alone, or one bound to an old head, is not enough.

## Catching what webhooks miss

Some state changes emit no reliable Actions event — a review thread being resolved/unresolved, a
check that silently never reports. Relying on events alone would let a PR sit falsely "ready" or
falsely "blocked." So the gate is driven by **both** events **and a scheduled sweep** over open
PRs targeting the default branch, oldest-updated-first. The sweep is what ultimately catches
thread resolution and missing check reports. The gate's own in-progress run is on the head, so an
event-driven run **defers** (does not merge) while its own check is pending and a later sweep
completes the merge — with **no name-substring exclusion**, which would be a bypass.

## Anti-tamper / enforcement

A gate a PR can edit away is not a gate.

- **The gate's definition and required-check set must live where a PR cannot change them.** The
  strong form is **org rulesets** (required checks + branch protection enforced org-wide from a
  place the repo/PR cannot edit) and **org-injected required/reusable workflows**, so a PR that
  deletes or edits a per-repo workflow file cannot remove the requirement. See
  [onboarding-and-config.md](onboarding-and-config.md).
- **Trusted authors and same-repo only.** Automation is driven only by trusted
  `author_association` on same-repo branches; **fork PRs never drive automation** and never reach
  a credential.
- **No self-approval, no gate-weakening.** Neither an implementer nor a reviewer principal can
  merge, approve its own work, or disable a required check. The `human-merge` label is a hard stop
  the gate always honours.

## What "done" means for the gate

The gate is correct only when every invariant above holds **and** there is a negative test for
each failure mode in [edge-cases.md](edge-cases.md). A green gate that was reached by trusting a
forgeable signal, an old-head success, or an unauthenticated check is a **defect**, not a pass.
