# Trust & correctness — why the gate cannot be tricked or bypassed

The gate is stagr's product. If it can be fooled into merging unready code, nothing else matters.
This page is the threat model and the invariants that make the gate sound. Every rule needs a
**static or behavioural test**: a static assertion on the rendered output, or a fixture with a
stubbed platform API.

> **What implements this.** The invariants are requirements for any merge gate stagr renders. The
> governance workflow stagr renders today (`stagr/platforms/github/_governance.py`) reads each
> stage's result signal and blocks a merge when a blocking stage fails; it does not merge. This
> repository's own merge gate, `.github/workflows/auto-merge-foundation-prs.yml` (see
> [`../../AGENTS.md`](../../AGENTS.md), "Merge lanes"), meets the invariants except for the gaps in
> [Known gaps](#known-gaps).

## The adversary

Per [`../../AGENTS.md`](../../AGENTS.md), all PR, issue and comment content is **untrusted data**.
The gate must stay correct when a PR author (or any actor who can comment, push or install an app)
tries to:

- forge a "passing" signal, edit a review summary, or delete or rename a workflow so no failing
  check exists;
- race a status change between the last read and the merge;
- open the merge with a stale success from an older commit;
- reach a credential or a stage the actor should never touch.

## Non-negotiable invariants

1. **Fail-closed, always.** Any signal that is missing, pending, unknown, malformed or errored
   means **not ready**. The gate only ever opens on an explicit, current, clean success. There is
   no "assume green."

2. **SHA-bound.** Predicates are evaluated on the current head SHA, and the merge call itself is
   pinned to that SHA, so the gate can never merge a *different* commit than the one it verified.

3. **Base-controlled definition and execution.** The gate workflow's definition **and** its token
   come from the trusted base branch, never from PR content. The gate **never checks out or
   executes PR code** and runs no repository-sourced script or action over PR content. On GitHub
   this is `pull_request_target` with no checkout of the head.

4. **No forgeable signal.** A signal any `statuses: write` actor could write is **never** trusted
   to *waive* a requirement. The description of a router or aggregate status is informational only;
   the gate re-derives readiness from first-class, identity-checked signals.

5. **Positive check identity.** A required external check is matched by **name and producing app**,
   not by name alone, so a same-named check from the wrong app cannot spoof it. The mandatory
   `validate` check requires both a completed successful check from the GitHub Actions app **and**
   a successful run of the `validate.yml` workflow file for the exact head, which closes the "delete
   or rename `validate.yml` so no failed check exists" hole.

6. **Reruns.** Only the latest attempt of a check counts, and the gate never falls back to an older
   success when a newer attempt exists. The foundation gate reads GitHub's check-runs list, which
   returns the latest attempt of each check by default.

7. **Re-read before merge.** After all predicates pass, the gate **re-reads fresh authoritative
   state, re-checks the mutable predicates and verifies the head has not moved** as the final step
   before the SHA-pinned merge. This narrows the gap between the last read and the merge but does
   **not** close it, because the predicates are not atomic with the merge. SHA-pinning guarantees it
   never merges a *different* commit, but between the final read and the merge call a
   `human-merge` label can be added, a review thread can reopen, or a check or review can turn
   blocking on the *same* SHA. **Server-side branch protection** closes some of these atomically
   (required checks, conversation resolution), which is why the gate's guarantees are layered on
   rulesets and are not a substitute for them. Branch protection **cannot** enforce the absence of
   the toolkit's `human-merge` label, so that race stays open unless the label is represented by a
   server-enforced signal such as a required status the label toggles (issue #43). The scheduled
   sweep bounds worst-case latency but does not make the step atomic.

## Sequencing code vs. security review

This repository runs the two reviews in sequence: the code review iterates per push until it
converges (completed and clean on the head), then a single security review is requested
(`request-final-security-review.yml`). The Stagr contract does not require that order. In the
`standard` profile the `review` and `security` stages are independent, and
[`../../design-docs/09-check-stages.md`](../../design-docs/09-check-stages.md) (section 10)
proposes that `security` declare `depends_on: [review]` so the renderer can enforce the order.

Either way, the gate requires a head-bound code review **and** a head-bound security review to
have completed. A security review alone, or one bound to an old head, is not enough.

The two hand-written request workflows use **separate** concurrency groups
(`request-codex-review-<PR>` and `request-codex-security`), so there is no shared lock between
them. A push that lands between the security workflow's head check and its comment post can let the
code-review request post too (see issue #29). Closing that window needs a shared lock or a single
dispatch authority.

## Catching what webhooks miss

Some state changes emit no reliable Actions event: a review thread being resolved or unresolved, or
a check that silently never reports. Relying on events alone would let a PR sit falsely "ready" or
falsely "blocked." So the gate is driven by **both** events **and a scheduled sweep** over open PRs
that target the default branch. The sweep is what catches thread resolution and missing check
reports.

Event runs use a **per-PR** concurrency group (`auto-merge-<PR>`) and the sweep uses a separate
one, so an event run and a sweep are **not serialized** and can overlap on the same PR. The
safeguards are **idempotent re-evaluation**, the **final re-read and head-move check** (invariant 7),
and the gate's own in-progress check run, which makes an event-driven run **defer** (not merge)
while its own check is pending so a later sweep completes the merge. The gate applies **no
name-substring exclusion** to check runs, because that would be a bypass.

## Anti-tamper / enforcement

A gate a PR can edit away is not a gate.

- **The gate's definition and its required-check set must live where a PR cannot change them.** The
  strong form is **org rulesets** (required checks and branch protection enforced org-wide from a
  place the repo or PR cannot edit) and **org-injected required or reusable workflows**, so a PR
  that deletes or edits a per-repo workflow file cannot remove the requirement. See
  [onboarding-and-config.md](onboarding-and-config.md).
- **Trusted authors and same-repo only.** Automation is driven only by trusted
  `author_association` on same-repo branches. **Fork PRs never drive automation** and never reach a
  credential.
- **No self-approval, no gate-weakening.** Neither an implementer nor a reviewer principal can
  merge, approve its own work or disable a required check. The `human-merge` label is a hard stop
  the gate always honours.

## Known gaps

These are open weaknesses in this repository's hand-written gate, each tracked in an issue:

- **Abbreviated review SHA (issue #23).** The review predicates accept Codex's summary row, which
  shows an abbreviated 7 to 40 character SHA, and compare it by **prefix**
  (`head_sha == row_sha*`). A commit crafted to share a reviewed head's short prefix could satisfy
  that fallback. The fix is exact binding to the full SHA.
- **Base retarget (issue #26).** `validate.yml` re-runs when a PR is **retargeted**, but the Codex
  code and security reviews are bound to the **head** SHA only, and the review-request workflow
  listens to new pushes (`synchronize`) only. A PR reviewed against one base and then retargeted to
  the default branch with the same head can be merged on stale review evidence even though the
  effective diff changed.
- **`human-merge` race (issue #43).** See invariant 7.

## What "done" means for the gate

The gate is correct only when every invariant above holds **and** there is a negative test for each
failure mode, including a forged signal, an old-head success, a same-named check from the wrong app
and a deleted `validate.yml`. A green gate that was reached by trusting a forgeable signal, an
old-head success or an unauthenticated check is a **defect**, not a pass.
