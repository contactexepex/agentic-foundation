# Stagr Neutral Core — GitHub + Codex Implementation Mapping

**Status:** Design phase — not yet implemented

---

## Overview

This document maps the neutral architecture objects to the current GitHub + Codex
implementation, identifies where the current implementation deviates from the contract,
and defines what the correct implementation looks like.

> This document describes the **current state** and the **target state**. It is an
> input to the implementation work, not a specification of the neutral core itself.

---

## Neutral-to-GitHub object mapping

| Neutral concept | GitHub implementation |
|---|---|
| `StageTrigger.PR_OPENED` | `pull_request_target: [opened, reopened, ready_for_review]` |
| `StageTrigger.PR_UPDATED` | `pull_request_target: [synchronize]` |
| `InvocationKind.PR_COMMENT` | `gh pr comment <pr> --body-file <file>` via CODEX_PAT |
| `EvidenceKind.REVIEW_RESULT` | Codex bot comment containing `codex-pull-request-review-summary` |
| `EvidenceKind.COMMENT_MATCH` | PR comment from the PAT account containing the in-flight marker |
| `StageResultSignal` | Commit status with context `stagr/stage/<stageId>` (target) |
| `RouteClassification` | Commit status with context `Publish fast review result` (current) |
| `TrustPolicy.trustedRoles` | `author_association` ∈ `["OWNER","MEMBER","COLLABORATOR"]` |
| `TrustPolicy.requireSameRepo` | `head.repo.full_name == GITHUB_REPOSITORY` check |
| `TrustPolicy.humanMergeLabel` | `human-merge` label |
| `MergePolicy.mode = AUTO` | Auto-merge via `auto-merge-foundation-prs.yml` |
| `MergePolicy.mode = MANUAL` | `human-merge` label present → gate stops |

---

## Current workflow → artifact class mapping

| Current workflow file | Artifact class | Stage |
|---|---|---|
| `request-codex-review-on-push.yml` | Stage execution artifact | `review` |
| `request-final-security-review.yml` | Stage execution artifact | `security` |
| `fast-ai-code-review.yml` | Routing artifact | (pipeline-level) |
| `auto-merge-foundation-prs.yml` | Governance / merge artifact | (pipeline-level) |

---

## The sequential dependency bug

### What the config declares

```yaml
stages:
  - id: review
    type: review
    dependencies: []    # independent

  - id: security
    type: security
    dependencies: []    # independent of review
```

Both stages declare `dependencies: []`. They are unconditionally independent.

### What the current implementation does

`request-final-security-review.yml` (lines 163–166) contains:

```bash
code_row="$(grep -i 'Code Review' <<<"$summary" | head -1 || true)"
grep -qi 'Completed' <<<"$code_row" \
  || { echo "code review is not yet completed; skipping."; return 0; }
code_sha="$(grep -oE '[0-9a-f]{7,40}' <<<"$code_row" | head -1 | tr -d '\`' || true)"
[[ -n "$code_sha" && "$head_sha" == "$code_sha"* ]] \
  || { echo "code review is bound to a different head; skipping."; return 0; }
```

This makes the security stage wait for the code review to complete before running.

### Why this violates the contract

This is a violation of **Renderer Invariant R1**: a renderer must not enforce a
dependency between two stages unless that dependency is declared in
`NormalizedStage.dependencies`. `security.dependencies` does not contain `review`.

The check was added to prevent concurrent code + security reviews because of an
observed backend issue. However, that behavior has not been empirically isolated — the
cause may be a race condition in the manual-comment invocation path, duplicate
requests, or workflow timing rather than a hard Codex backend limitation. OpenAI's
official documentation describes Code Review and Security Review as independently
triggerable.

**Until empirical testing demonstrates a true backend concurrency constraint, no
serialization between these two independent stages should be encoded in the
architecture or the generated artifacts.**

---

## Target design: independent triggers

Under the correct architecture, both stage execution artifacts trigger independently on
every push to an eligible PR.

### Declared StageTriggers vs reconciliation events

There is an important distinction in the GitHub implementation between two categories of
workflow triggers:

| Category | GitHub event | What it means |
|---|---|---|
| **Declared StageTrigger** | `pull_request_target: [synchronize]` | Maps to `StageTrigger.PR_UPDATED`; starts a new invocation |
| **Reconciliation event** | `issue_comment: [created, edited]` | Wakes the workflow to check if a pending invocation has completed |
| **Reconciliation event** | `check_suite: [completed]` | Wakes the workflow to check if a pending invocation has completed |

`issue_comment` and `check_suite` events do **not** map to any `StageTrigger` value.
They are renderer-internal wakeups used by the reconciliation loop to observe backend
completion after an invocation has been posted. They never cause a new invocation to be
posted on their own. See `06-runtime-boundary.md` for the reconciliation model.

### review stage execution artifact

```
Declared triggers (StageTrigger.PR_OPENED + StageTrigger.PR_UPDATED):
  pull_request_target [opened, reopened, ready_for_review]  ← PR_OPENED
  pull_request_target [synchronize]                          ← PR_UPDATED
    → Resolve PR, enforce TrustPolicy, check idempotency, check routing
    → If all pass: post @codex review with in-flight marker
    → Emit StageResultSignal (state=RUNNING, conclusion=UNKNOWN)

Reconciliation events (implementation detail, not StageTrigger):
  issue_comment [created, edited] OR check_suite [completed]
    → Resolve PR, check EvidenceSpec for headSha
    → If evidence found: evaluate GateDispositionSpec, emit updated StageResultSignal
    → (state=COMPLETED, conclusion=PASS|BLOCKED)
```

### security stage execution artifact

```
Same structure as review.
Declared triggers: pull_request_target [opened, reopened, ready_for_review, synchronize]
  (PR_OPENED → opened/reopened/ready_for_review; PR_UPDATED → synchronize)
Reconciliation events: issue_comment [created, edited], check_suite [completed]
```

Both artifacts trigger independently on the same declared StageTrigger events
(`PR_OPENED` and `PR_UPDATED`). Neither waits for the other.

### Codex Evidence path

The current Codex `@codex security review` invocation via PR comment may not reliably
update the Security Review row in the Codex summary comment — this was the reason the
current implementation uses the comment-ordering fallback. The EvidenceSpec for the
security stage must describe an evidence path that actually works for this invocation
method. **Until this is verified empirically, the EvidenceSpec for the security stage
should not assume the Codex summary row is reliably updated by a PR-comment–triggered
security review.**

Options to investigate:
1. Does `@codex security review` posted as a PR comment update the Codex summary row?
   If yes, use `REVIEW_RESULT` evidence.
2. If not, does the Codex bot post a separate completion comment? Use `COMMENT_MATCH`
   evidence targeting that comment's format.
3. Is there a native Codex Security Review configuration (not comment-triggered) that
   produces reliable summary row updates? If so, use that invocation path and update
   the EvidenceSpec accordingly.

The EvidenceSpec for the security stage must be determined empirically before the stage
execution artifact for security is implemented.

---

## StageResultSignal: what needs to be added

The current implementation does not emit normalized `StageResultSignal` values. The
auto-merge gate (`auto-merge-foundation-prs.yml`) directly reads Codex summary comment
rows instead of normalized signals.

To conform to the architecture:

1. Each stage execution artifact must emit a `StageResultSignal` as a commit status
   (or check run) after evaluating its EvidenceSpec.
2. The governance artifact (`auto-merge-foundation-prs.yml`) must read these commit
   statuses instead of Codex comment rows.
3. This decouples the governance artifact from Codex-specific output formats and makes
   it work correctly with any future backend.

---

## What does NOT need to change in the neutral config

The `.agentic/config.yml` is already correct:

```yaml
stages:
  - id: review
    type: review
    dependencies: []   ✓ correct — independent
  - id: security
    type: security
    dependencies: []   ✓ correct — independent
```

The bug is entirely in the rendered implementation. The neutral config needs no changes.

---

## Summary of changes needed in the implementation

| Item | Change required |
|---|---|
| `request-final-security-review.yml` | Remove code-review-completion gate. Add `pull_request_target: [opened, reopened, ready_for_review, synchronize]` triggers (PR_OPENED + PR_UPDATED). Both stages trigger independently. |
| `request-codex-review-on-push.yml` | Add `pull_request_target: [opened, reopened, ready_for_review]` triggers (PR_OPENED). Remove 3-minute security-review serialization wait (lines 218–237). Emit `StageResultSignal` after evidence check. |
| Both stage workflows | Add in-flight idempotency marker (`<!-- stagr:stage:<id>:<sha> -->`). Emit `StageResultSignal` to commit status. |
| `auto-merge-foundation-prs.yml` | Read `StageResultSignal` commit statuses instead of Codex summary comment rows. |
| New: provider configuration | Add secret alias → platform secret name mapping (TRUSTED_COMMENTER_TOKEN → REMEDIATION_TOKEN) to provider config. |
| Verify empirically | Test whether `@codex security review` PR comment reliably updates the Codex summary Security Review row before implementing the EvidenceSpec. |
