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
   **Base-retarget gap [target].** Evidence is bound to the **head** SHA only — `validate.yml` and
   `request-review.yml` do not re-trigger on a **base change** (retarget). So a PR reviewed/validated
   against one base and then **retargeted to the default branch with the same head** can be merged on
   **stale evidence** while `mergeable_state == clean`, even though the effective diff changed. Binding
   evidence to the base revision (or invalidating + rerunning on retarget) is an open hardening item.

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
   the residual race can admit a **now-unready commit**, not merely defer it. **Server-side branch
   protection** closes *some* of these atomically — required checks and conversation-resolution —
   which is why the gate's guarantees are layered on org rulesets rather than a substitute for them.
   But branch protection **cannot** enforce the absence of the toolkit-specific **`human-merge`
   label**: a label added after the final read can still lose to the merge PUT. So the `human-merge`
   race remains an **irreducible residual** unless it is represented by a server-enforced gate signal
   (e.g. a required status the label toggles). The scheduled sweep bounds worst-case latency but does
   not make the step atomic.

## Sequencing code vs. security review

The Codex backend **errors if a code review and a security review run concurrently** on one PR.
Therefore:

- the **code-review loop runs per push** until it converges (completed + clean on the head);
- the **single security review** is triggered **only after** convergence;
- the security-review workflow **serializes its own runs** (concurrency group `request-codex-security`).

**Honest residual [target].** The code-review and security-review *request* workflows use **separate**
concurrency groups (`request-codex-review-*` per PR vs. `request-codex-security`), so there is **no
shared cross-workflow lock**. A push landing in the security workflow's **check-to-post window**
(after it verifies the head but before its comment POST, and before Codex flips the summary row to
`Running`) can let the code-review request post too — a narrow window where both could be requested.
"Never concurrent" is therefore the **design intent**, achieved by converge-then-request plus
per-workflow serialization; fully closing the window needs a **shared lock or a single dispatch
authority** ([roadmap.md](roadmap.md)).

Either way, the gate requires a head-bound code review **and** a head-bound security review to have
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
  **deletes or renames** a per-repo workflow file cannot bypass the required-check gate. A PR can
  still **replace** the workflow body with a trivially passing job while keeping the same path and
  check name — the ruleset still accepts it because the check identity (name + App id) matches.
  Protecting against that requires an org-controlled or base-ref-protected check producer, which is
  outside this toolkit's current scope. See [onboarding-and-config.md](onboarding-and-config.md).
- **Trusted authors and same-repo only.** Automation is driven only by trusted
  `author_association` on same-repo branches; **fork PRs never drive automation** and never reach
  a credential.
- **No self-approval, no gate-weakening.** Neither an implementer nor a reviewer principal can
  merge, approve its own work, or disable a required check. The `human-merge` label is a hard stop
  the gate always honours.

## Org-ruleset provisioning

### Why org rulesets, not per-repo branch protection

GitHub's per-repo branch protection lives in the repository itself. A PR that edits
`.github/workflows/` or the branch-protection settings API can weaken or remove the gate from
within the repository — exactly the threat the "Anti-tamper / enforcement" section above describes.

**Org rulesets** (GitHub REST: `POST /orgs/{org}/rulesets`) are enforced from a place a repo or a PR
inside the repo cannot edit:

- Only an **org owner or admin** can create, modify, or delete an org ruleset.
- The ruleset applies across selected (or all) repos without any per-repo config file that a PR
  could overwrite.
- Required checks and branch protection rules enforced by an org ruleset are **not bypassable** by
  a repo-level actor.

This is why the gate's layered guarantee is built on org rulesets rather than a substitute for them
(see invariant 7 above).

### Required ruleset settings

The reference template configures the following settings:

| Setting | Value | Why |
|---|---|---|
| `pull_request` rule | (present) | Prevents direct pushes to the default branch; requires a pull request so the gate has something to evaluate. |
| `dismiss_stale_reviews_on_push` | `true` | A commit pushed after a human approval invalidates that approval, so a human-lane re-approval on the new head is real. Without this, an approval on an old head survives a force-push or additional commit. |
| `required_review_thread_resolution` | `true` | Prevents a race where a review thread is reopened after the gate's final read but before the merge PUT. |
| `required_status_checks` rule | (present) | Forces at least the `Validate` check and the `Publish fast review result` router status to pass before merge, server-side — preventing the "delete or rename validate.yml" bypass. Note: this prevents bypassing the gate via deletion or rename; it does **not** prevent a trusted author from replacing the workflow body with a trivially passing job (see the anti-tamper note above). **Scope:** requiring `Publish fast review result` enforces that the routing workflow ran, but does **not** enforce Codex-review completion. That enforcement is the sole responsibility of the rendered `auto-merge-foundation-prs.yml` gate, which checks for head-bound code and security reviews before merging. Any principal with merge permission (a human, or a workflow token with sufficient scope) can merge via the REST API or the GitHub UI as soon as only these two checks are green — before Codex reviews complete. Foundation-lane repos address this through the auto-merge gate being the only actor that calls the merge API; human-lane repos rely on reviewer discipline. |
| `strict_required_status_checks_policy` | `true` | PRs must be up-to-date with the base branch before merging, preventing a merge against a stale base. |
| `do_not_enforce_on_create` | `true` | Newly created repositories can push their initial default branch without required status checks blocking the bootstrap push. |

> **Foundation-lane note.** The reference template sets `"required_approving_review_count": 0`
> (no approvals required). The foundation lane's auto-merge does not create a human approval, so
> requiring one would block automated merges. Repos that use the human-gated lane should set this
> to `"required_approving_review_count": 1` when applying this template.

A reference template is at
[`rulesets/org-branch-protection.json`](rulesets/org-branch-protection.json). It is a **reference
only** — not executable as-is. Before applying it:

1. Replace `integration_id: null` in each `required_status_checks` entry with the **numeric GitHub
   App id** of the app that posts each check (the Validate runner and the router status poster).
   Using the app id prevents a same-named check from a different app from satisfying the requirement
   (see invariant 5 above). To find the numeric App ID, query the GitHub API:
   ```
   GET https://api.github.com/apps/{app-slug}
   ```
   The `id` field in the response is the numeric App ID. For status checks produced by GitHub
   Actions workflows the app slug is `github-actions`. Leave `integration_id: null`
   if the check producer is not a GitHub App (e.g. a third-party CI service that posts a commit
   status directly via the Statuses API).
2. Scope `repository_name.include` to the repos you want covered. **Caution with `~ALL`:** applying
   the ruleset org-wide means every repo must produce both the `Validate` and
   `Publish fast review result` checks on every PR. A repo that has not yet run `stagr apply`
   cannot produce those checks, and every PR on it will be permanently blocked. Scope to only
   onboarded repos (by an explicit list or a naming convention) until the whole org is onboarded.
3. Apply via the GitHub API (`POST /orgs/{org}/rulesets`) or the org's **Rules → Rulesets** UI, as
   an org owner.

### What the provisioning step is and is not

stagr is a **control plane**: it declares, initializes, and governs — it does not execute the
provisioning call itself. Provisioning the org ruleset is a **one-time manual (or scripted) operator
step** performed by an org admin. The reference JSON is the declaration; applying it is the operator's
job.

Automated provisioning verification (`doctor` checking that the ruleset is installed with the correct
settings) is a **[target]** item — see [roadmap.md](roadmap.md).

## What "done" means for the gate

The gate is correct only when every invariant above holds **and** there is a negative test for
each failure mode in [edge-cases.md](edge-cases.md). A green gate that was reached by trusting a
forgeable signal, an old-head success, or an unauthenticated check is a **defect**, not a pass.
