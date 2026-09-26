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

2. **SHA-bound.** Predicates are evaluated on the current head SHA, and the merge call itself is
   SHA-pinned, so the gate can never merge a *different* commit than the one it verified. **One honest
   gap [target]:** the review predicates prefer a canonical review **object** matched on the **full**
   `commit_id == head_sha` (exact), but they **fall back** to a visible Codex summary row whose SHA is
   matched by **prefix** (`head_sha == row_sha*`), which accepts an abbreviated 7–40-char SHA. A
   commit crafted to share a reviewed head's short prefix could satisfy the fallback. Removing the
   abbreviated fallback in favour of the full machine-readable marker/object (exact-only binding) is
   an open hardening item ([roadmap.md](roadmap.md)).

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
   state, re-checks the mutable predicates, and verifies the head has not moved** as the final step
   before the SHA-pinned merge. This narrows — but does **not** close — the last-read→merge race:
   SHA-pinning guarantees it can never merge a *different* commit, but the mutable predicates are
   **not atomic** with the merge. Between the final read and the merge PUT, a `human-merge` label can
   be added, a review thread can reopen, or a check/review can turn blocking on the *same* SHA — so
   the residual race can admit a **now-unready commit**, not merely defer it. Only **server-side
   branch protection** closes these predicates atomically; that is why the gate's guarantees are
   layered on org rulesets, not a substitute for them. The scheduled sweep bounds worst-case latency
   but does not make the step atomic.

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
PRs targeting the default branch. The sweep is what ultimately catches thread resolution and
missing check reports.

- **Concurrency [shipped].** Event runs use a **per-PR** group (`auto-merge-<PR>`) and the sweep a
  separate group, so a per-PR event and a sweep are **not globally serialized** and can overlap on
  the same PR. The safeguards are **idempotent re-evaluation**, the **final re-read + head-move
  check** (invariant 7), and the gate's own in-progress check-run — which makes an event-driven run
  **defer** (not merge) while its own check is pending, so a later sweep completes the merge — with
  **no name-substring exclusion**, which would be a bypass. (Global serialization *is* used,
  correctly, for the separate security-review workflow — see the sequencing section above — but the
  merge gate is per-PR, not globally serialized.)
- **Ordering [shipped/target].** The final-security-review sweep processes PRs
  **oldest-updated-first [shipped]**; the **auto-merge sweep currently uses GitHub's default
  ordering**, so adding an explicit oldest-updated ordering to bound worst-case merge latency under
  many open PRs is a **[target]** hardening item ([roadmap.md](roadmap.md)).

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
