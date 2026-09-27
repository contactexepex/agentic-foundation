# Stagr Neutral Core — Runtime Boundary

**Status:** Design phase — not yet implemented

---

## Overview

Stagr operates exclusively at render time. Once `stagr apply` has written platform
artifacts, Stagr's job is done. Everything that follows — PR events, stage invocations,
evidence collection, result signalling, and merge decisions — happens entirely inside
the platform and the generated artifacts.

---

## What Stagr does and does not do

### At render time (`stagr apply`)

- Parse and validate `.agentic/config.yml`
- Expand profiles, normalize stages, derive `MergePolicy.blockingStageIds`
- Invoke BackendRenderer per stage → `ExecutionPlan`
- Invoke PlatformRenderer per stage → stage execution artifact
- Invoke PlatformRenderer for pipeline → routing artifact + governance artifact
- Write all artifacts to the target directory

### Never at run time

Stagr is never involved in:

- Listening to GitHub webhook events
- Posting PR comments
- Calling model provider APIs
- Checking review status
- Inspecting commit diffs
- Deciding whether to merge a PR
- Any network call after `stagr apply` completes

---

## EvidenceSpec — raw completion detection

An `EvidenceSpec` is a backend-supplied, platform-renderer–consumed description of how
raw stage completion is detected. It bridges the backend's output format with the
platform's event/API model. The neutral contract knows only the structure; the meaning
of `selector` is opaque to it.

```
EvidenceSpec {
  kind:             EvidenceKind
  selector:         string             // backend-defined; opaque to neutral contract
  correlation:      CorrelationSpec
  successCondition: EvidenceSuccessCondition
}
```

### EvidenceKind — semantic vocabulary

Evidence kinds are named for what they represent semantically, not for platform objects.
The PlatformRenderer maps each semantic kind to the appropriate platform API.

| Value | Semantics | GitHub mapping |
|---|---|---|
| `REVIEW_RESULT` | A formal review object produced by a reviewer agent | Codex summary comment containing a structured review table |
| `COMMENT_MATCH` | A PR comment matching a content selector | PR issue comment where `body` contains `selector` |
| `CHECK_RESULT` | A CI check run with a pass/fail conclusion | GitHub check run on the head commit |
| `WORKFLOW_RESULT` | A CI workflow run with a pass/fail conclusion | GitHub Actions workflow run |

Using semantic vocabulary keeps EvidenceSpec portable: a `REVIEW_RESULT` on GitHub is
a comment with a specific format; on GitLab it might be a note on an MR. The renderer
handles the mapping; the EvidenceSpec stays neutral.

### CorrelationSpec

Specifies how to bind an evidence item to the correct head commit, preventing a stale
evidence item from satisfying a check on a newer commit.

```
CorrelationSpec {
  headSha:      boolean   // true = evidence must be correlated to the current head SHA
  shaField:     string    // which field within the evidence item carries the SHA value
                          // (backend-defined; e.g. "first code block in Code Review row")
}
```

When `headSha: true`, the stage execution artifact must extract the SHA from `shaField`
and verify it matches the current head SHA before accepting the evidence as valid.

### EvidenceSuccessCondition

| Value | Meaning | Example |
|---|---|---|
| `SUCCESS` | The operation passed with no failures. A failed result means the condition is NOT met. | Test suite green, build passed |
| `COMPLETED` | The operation finished processing, regardless of findings. A review with 5 findings is COMPLETED. | Code review, security review |
| `MATCH_FOUND` | A specific pattern is present in the evidence. | A specific string in a comment body |

> **Key point:** `COMPLETED` means "the reviewer finished." It does NOT mean "the
> result satisfies the merge gate." Gate satisfaction is determined by
> `StageResultConclusion`, not by `EvidenceSuccessCondition`.

---

## GateDispositionSpec — PASS vs BLOCKED logic

`EvidenceSpec` models raw completion detection. It answers: "Did the backend finish
processing?" It cannot answer: "Did the backend finish with no blocking findings?" These
are distinct questions that require distinct specifications.

`GateDispositionSpec` answers the second question: given that evidence of completion
exists, is the result PASS or BLOCKED?

```
GateDispositionSpec {
  kind:     GateDispositionKind
  selector: string   // backend-defined; opaque to neutral contract
}
```

### GateDispositionKind

| Value | Meaning | Example |
|---|---|---|
| `NO_OPEN_THREADS` | PASS if the platform reports zero unresolved review threads linked to this stage's invocation | Codex review with all threads resolved |
| `EXPLICIT_PASS_MARKER` | PASS if a specific completion marker is present in the backend's output | A comment containing `stagr:pass:<stageId>` |
| `ALWAYS_PASS` | PASS whenever the evidence condition is met (no separate gate check) | Build/test stages: success = PASS |

```
GateDispositionSpec {
  kind:     GateDispositionKind
  selector: string              // backend-defined; opaque to neutral contract
  scope:    FindingScopeSpec | null  // required for NO_OPEN_THREADS; null otherwise
}
```

### FindingScopeSpec

`FindingScopeSpec` constrains which review threads count as "open threads linked to this
stage's invocation" for `NO_OPEN_THREADS`. Without it, the governance artifact would
count all unresolved threads on the PR — including threads from other stages or
pre-existing discussions unrelated to this stage's run.

```
FindingScopeSpec {
  createdBy: string    // only count threads from comments posted by this account/identity
  headSha:   boolean   // true = only count threads linked to the current head SHA
}
```

Example: for the Codex review stage, `createdBy` would be set to the Codex bot's identity
and `headSha: true` so that only threads from the Codex review of the current head commit
are counted.

The BackendRenderer supplies both `EvidenceSpec` (when done?) and `GateDispositionSpec`
(PASS or BLOCKED?). The PlatformRenderer uses both to write the observation logic inside
the stage execution artifact.

---

## StageResultSignal — normalized runtime result

The `StageResultSignal` is the normalized result that stage execution artifacts emit and
the governance artifact consumes. It is the canonical bridge between raw backend
evidence and merge governance.

```
StageResultSignal {
  stageId:    string
  headSha:    string
  state:      StageResultState
  conclusion: StageResultConclusion
}
```

### StageResultState

| Value | Meaning |
|---|---|
| `PENDING` | Stage has not started or invocation has not been posted yet |
| `RUNNING` | Stage invocation is in flight; backend is processing |
| `COMPLETED` | Backend finished processing (findings may be present) |
| `FAILED` | Stage could not finish (infra failure, timeout, dependency failure) |

### StageResultConclusion

| Value | Meaning |
|---|---|
| `PASS` | Stage completed; result satisfies the merge gate |
| `BLOCKED` | Stage completed; blocking findings or conditions prevent gate pass |
| `FAILED` | Stage did not finish successfully |
| `UNKNOWN` | Signal malformed or cannot be interpreted |

### How a stage execution artifact determines conclusion

For `REVIEW` and `SECURITY` stages (typical case):

```
evidence state  →  state = COMPLETED
no unresolved findings linked to this stage  →  conclusion = PASS
unresolved findings linked to this stage  →  conclusion = BLOCKED
```

For `TEST` and `BUILD` stages:

```
check run conclusion = success  →  state = COMPLETED, conclusion = PASS
check run conclusion = failure  →  state = COMPLETED, conclusion = FAILED
```

> **Note on "unresolved findings":** The stage execution artifact determines findings
> via its `EvidenceSpec`. For comment-based review backends, findings manifest as
> unresolved review threads. The stage execution artifact counts these and sets
> `conclusion = BLOCKED` when any are present. The governance artifact reads only the
> `StageResultSignal` — it does not count threads itself.

### Signal emission

The stage execution artifact emits the `StageResultSignal` to a well-known, per-stage
platform location declared in the `StageResultSpec`. The governance artifact reads this
location to evaluate merge eligibility.

**Provenance requirement.** A `StageResultSignal` is a trust boundary: the governance
artifact uses it to decide whether to auto-merge. If any actor with `statuses: write`
permission could publish or overwrite these signals, the merge gate is forgeable. The
signal must be published using a platform mechanism that carries authenticated publisher
identity.

On GitHub:
- **Recommended: Check Runs.** A check run is associated with the GitHub App that creates
  it. The governance artifact can verify the App identity before trusting the result.
  Commit statuses can be created by any token with `statuses: write` and carry no App
  identity — they are forgeable in this threat model.
- Stage execution artifacts should create check runs (not commit statuses) for
  `StageResultSignal` emission. The `StageResultSpec.signalKind` value `CHECK_RUN` is
  the correct choice.

The `StageResultSignalKind` values reflect this distinction: `CHECK_RUN` (authenticated
App identity), `COMMIT_STATUS` (any `statuses: write` actor — use only when Check Runs
are not available for the target backend), `WORKFLOW_OUTPUT`.

---

## Reconciliation model

After an invocation is posted and an initial `StageResultSignal` is emitted
(`state = RUNNING, conclusion = UNKNOWN`), the backend processes the request
asynchronously. The stage execution artifact must update the signal when the backend
completes — this is the **reconciliation loop**.

### Reconciliation triggers

Reconciliation events are platform-level wakeups that re-evaluate pending stage signals.
They are **not** declared `StageTrigger` values; they are renderer-internal mechanism.

| Event (GitHub) | When it fires |
|---|---|
| `issue_comment` (created/edited) | When a new comment appears on the PR — the backend may have posted its result |
| `check_suite` (completed) | When a CI check suite finishes — covers check-run–based backends |
| Scheduled sweep | Periodic re-evaluation to recover from missed events (e.g., cron every 5 minutes) |

On each reconciliation event, the stage execution artifact:

1. Resolves the PR and head SHA
2. Checks the `EvidenceSpec` for the current head SHA — has the backend produced evidence?
3. If yes, evaluates the `GateDispositionSpec` — PASS or BLOCKED?
4. Emits an updated `StageResultSignal` (`state = COMPLETED, conclusion = PASS|BLOCKED`)

**Reconciliation termination rule.** A stage execution artifact stops re-evaluating a
signal only when it reaches a terminal state that cannot change without a new push:

- `COMPLETED + PASS` — the gate condition is satisfied; re-evaluation adds no value.
- `FAILED` (irrecoverable) — infrastructure failure, dependency failure, or similar
  non-recoverable condition.

**`COMPLETED + BLOCKED` is not terminal for reconciliation.** A BLOCKED conclusion means
the backend finished but found blocking issues. Those issues can be resolved (e.g.,
threads closed, findings addressed) without a new push. The stage execution artifact
**must** continue re-evaluating on each reconciliation event to detect when the BLOCKED
condition clears and a PASS can be emitted.

**Recovery rule for expired in-flight markers.** When the reconciliation sweep runs and
all of the following hold, the artifact may post a fresh invocation:
1. A stage invocation was previously posted for the current head SHA (in-flight marker
   exists for this head SHA).
2. No completion evidence exists for this head SHA (the backend has not responded).
3. The in-flight marker's expiry timestamp has passed.

In this case, the artifact treats the marker as absent and re-posts the invocation,
setting a new expiry. This recovers from backend outages or dropped invocations without
requiring a new push.

### Why reconciliation is separate from StageTrigger

`StageTrigger` values (`PR_OPENED`, `PR_UPDATED`, `MANUAL`) declare when a stage's
*invocation* is requested. They are part of the neutral config and appear in
`NormalizedStage.triggers`. Reconciliation events are implementation details of how a
stage execution artifact *observes* backend completion after the invocation has been
posted. They are not visible in the neutral config.

---

## RouteClassification — routing runtime signal

```
RouteClassification {
  route:   FAST | NORMAL
  headSha: string
}
```

The routing artifact emits this as a commit status on the PR head commit. The
governance artifact reads it as part of merge eligibility evaluation.

Head SHA binding is mandatory. Without it, a stale `FAST` classification for a prior
commit could cause the governance artifact to skip blocking stages for a new commit.

---

## Idempotency

Stage execution artifacts that invoke backends via PR comments must be idempotent across
two distinct failure modes:

### 1. Completion idempotency

Guard: "Has this stage already completed for this head SHA?"

Mechanism: EvidenceSpec-based check. Before posting an invocation, the stage execution
artifact evaluates the EvidenceSpec against the current head SHA. If evidence of
completion already exists and is bound to this SHA, skip the invocation.

This is the steady-state guard (once done, stay done).

### 2. In-flight idempotency

Guard: "Has an invocation for this head SHA already been posted and is in flight?"

Mechanism: A durable per-head, per-stage marker embedded in the invocation comment
(for `PR_COMMENT` backends). Format:

```
<!-- stagr:stage:<stageId>:<headSha> -->
```

This marker is invisible to human readers and to the backend. Before posting an
invocation, the stage execution artifact checks whether a comment from the trusted
posting account already contains this marker for the current head SHA. If yes, skip.

This guard covers the window between posting the invocation and the backend updating
its evidence (before the completion guard can pass).

### In-flight marker expiry (lease semantics)

An in-flight marker without expiry can permanently strand a PR if the backend never
accepts the invocation (network failure, backend outage, malformed request). To prevent
this, each invocation comment must include an expiry timestamp alongside the marker:

```
<!-- stagr:stage:<stageId>:<headSha>:expires:<ISO8601-timestamp> -->
```

Before treating an existing marker as valid, the stage execution artifact checks whether
the expiry has passed. If expired, the marker is treated as absent and a fresh invocation
is posted. The expiry window is a per-backend configuration value rendered into the stage
execution artifact at render time (e.g., 30 minutes for a typical review backend).

The two guards are complementary:
- Completion guard: steady state — already done, don't re-invoke
- In-flight marker: transient window — invocation posted, backend not yet responding
  (expires after the configured lease window; re-invocation happens on next eligible event)
