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
  producedBy:       string | null      // identity that authors the evidence item
}
```

### producedBy — evidence authenticity

PR content is untrusted: on a public repository anyone can post a comment that copies a
backend's selector text and the (public) head SHA. `producedBy` names the identity that
authors genuine evidence (mirroring `FindingScopeSpec.createdBy`, which does the same for
findings). The stage execution artifact must ignore any evidence item authored by another
identity.

- It is **required** for comment-based evidence (`REVIEW_RESULT`, `COMMENT_MATCH`). A
  PlatformRenderer must reject such a plan at render time when it is missing, rather than
  fall back to an unauthenticated match.
- The identity string is platform-defined (a login on GitHub). Bot identities must not be
  matched against look-alike human accounts: a login ending in `[bot]` matches only a
  platform Bot actor.

### EvidenceKind — semantic vocabulary

Evidence kinds are named for what they represent semantically, not for platform objects.
The PlatformRenderer maps each semantic kind to the appropriate platform API.

| Value | Semantics | GitHub mapping |
|---|---|---|
| `REVIEW_RESULT` | A formal review object produced by a reviewer agent | Codex summary comment containing a structured review table |
| `COMMENT_MATCH` | A PR comment whose body satisfies the backend-defined selector expression | PR issue comment evaluated against the backend-defined `selector` (see compound selector convention below) |
| `CHECK_RESULT` | A named result authored by a named producer, with a pass/fail conclusion (an `observed` stage, `09-check-stages.md`) | GitHub check run on the head commit, matched by name and author |
| `WORKFLOW_RESULT` | The platform's own outcome of the work unit a `commands` stage runs (`09-check-stages.md`) | Result of the workflow job that ran the commands |

Using semantic vocabulary keeps EvidenceSpec portable: a `REVIEW_RESULT` on GitHub is
a comment with a specific format; on GitLab it might be a note on an MR. The renderer
handles the mapping; the EvidenceSpec stays neutral.

#### Compound selector convention for COMMENT_MATCH

The `selector` field in `EvidenceSpec` is **backend-defined and opaque to the neutral
contract**. The baseline semantic is that the comment body contains the selector string.
BackendRenderers that need predicate filtering beyond simple string containment — for
example, to distinguish a completed marker from a running one inside the same marker
format — may use the following compound selector convention, which the PlatformRenderer
for that backend must implement:

```
<marker-prefix> [key=value ...]
```

- The first space-delimited token is a **literal prefix** matched by simple string
  containment against the comment body. `MATCH_FOUND` requires this prefix to be present.
- Each subsequent `key=value` token is a **JSON field predicate**: the comment body must
  contain the marker prefix, and the JSON blob inside the marker must have a field named
  `key` whose value equals `value` (string comparison). All predicates must be satisfied.

**Example:** the selector `codex-security-review:v1 status=completed` requires:
1. The comment body contains the literal string `codex-security-review:v1`.
2. The JSON object inside the marker has `"status": "completed"`.

A marker with `"status": "running"` satisfies the prefix but not the predicate, so
`MATCH_FOUND` is NOT triggered. This allows a single marker format to represent both
in-progress and completed states without requiring separate marker types.

BackendRenderers that use the compound format must document it in their module docstring.
BackendRenderers that require only simple string containment use a plain prefix string
with no `key=value` tokens; the two forms are unambiguous.

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
  createdBy:             string         // only count threads from comments posted by this identity
  headSha:               boolean        // true = only count threads linked to the current head SHA
  invocationCorrelation: string | null  // backend-defined; a per-invocation discriminator
                                        // the PlatformRenderer uses to distinguish this stage's
                                        // threads from those of another stage posted by the same
                                        // identity on the same head
}
```

`invocationCorrelation` is necessary when two stages share the same bot identity and head
SHA. For example, when both `review` and `security` are posted by the same Codex bot on
the same head commit, `createdBy + headSha` alone cannot distinguish their threads.
`invocationCorrelation` provides the discriminator — a backend-defined, opaque string that
the PlatformRenderer uses to identify which platform objects (threads, review objects, or
other finding artifacts) belong to this specific stage's invocation.

The concrete binding of `invocationCorrelation` to a platform-observable primitive is a
BackendRenderer + PlatformRenderer implementation detail, not a neutral-contract concern.
Candidate bindings on GitHub:
- A `pull_request_review_id` — if the backend creates a formal GitHub PR Review object
  per stage invocation, threads associated with that review share a stable review ID that
  the PlatformRenderer can filter on.
- A backend-emitted correlation marker included in every finding comment body — the
  PlatformRenderer filters threads whose body contains the marker string.
- A backend-specific task or invocation identifier exposed in the backend's completion
  artifact and echoed into each finding.

**Binding requirement:** the chosen binding must be reliably observable through the
platform's review-thread API. For `NO_OPEN_THREADS` to be safe on GitHub, the binding
must unambiguously associate each review thread with its originating stage invocation
using a field the GitHub review-thread API actually exposes (e.g., `pull_request_review_id`,
not a back-reference to the triggering issue comment, which the API does not provide).

**V1 conservative fallback (shared-scope mode).** When a spike investigation demonstrates
that no reliable per-invocation binding is available for a given backend — for example,
Spike B found that the GitHub API does not expose a reliably observable field that
unambiguously associates individual review threads with their originating stage invocation
when two reviews run under the same Codex bot identity on the same head commit — the
BackendRenderer may use `NO_OPEN_THREADS` with `invocationCorrelation=null` as a
conservative V1 fallback. In this mode the gate is scoped only by `createdBy + headSha`:
all unresolved threads from that bot identity on the current head must be resolved before
any stage using this disposition passes. The intentional consequence is **cross-stage
blocking**: a finding from the REVIEW stage will keep the SECURITY stage BLOCKED, and
vice versa. This is fail-closed behavior, not a bug. The BackendRenderer's module
docstring must explicitly document this V1 shared-scope mode and the Spike finding that
motivates it. The V1 fallback is not a general licence to omit `invocationCorrelation`;
it requires documented spike evidence that no reliable binding exists for this specific
backend.

**Gate-semantics constraint:** the V1 fallback is only valid when **all** stages that
share the bot identity and head SHA are configured with `BLOCKING` gate semantics. If
any co-sharing stage is configured `NON_BLOCKING` (advisory), the shared scope silently
causes that stage's unresolved findings to block every `BLOCKING` stage in the shared
scope, contradicting the user's explicit advisory-gate intent. In that situation the
BackendRenderer must not apply `NO_OPEN_THREADS` with shared scope to either the
advisory stage or any blocking stage sharing its identity; an alternative disposition
must be chosen instead.

When `invocationCorrelation` is null without a documented spike, `createdBy + headSha` is
sufficient only when stages use distinct bot identities.

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
| `FAILED` | Stagr could not evaluate the stage (infrastructure or API failure, ambiguous evidence) |

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

For `TEST` and `BUILD` stages, and any other `commands` or `observed` stage (the full table
is in `09-check-stages.md`):

```
outcome = success                                  →  state = COMPLETED, conclusion = PASS
failure, timed out, cancelled, skipped, neutral    →  state = COMPLETED, conclusion = FAILED
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
artifact uses it to decide whether to auto-merge. The signal must be published using a
platform mechanism that carries authenticated publisher identity, and the governance
artifact must verify that identity before trusting the result.

On GitHub V1:
- **Required: Check Runs.** A check run is associated with the GitHub App that creates
  it. The publisher's App ID is verifiable. Commit statuses carry no App identity and
  are forgeable by any token with `statuses: write` — they are **not permitted** for
  `StageResultSignal` on GitHub V1.
- Stage execution artifacts must create check runs for `StageResultSignal` emission.
  The `StageResultSpec.signalKind` must be `CHECK_RUN`.
- The governance artifact must verify the check run's publisher identity matches the
  `StageResultSpec.provenance.publisherIdentity` rendered into the governance artifact
  at render time. A check run from an unexpected App or workflow is rejected.

`StageResultSignalKind` has one value, `CHECK_RUN` (authenticated App identity). A commit
status is not permitted on GitHub V1.

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
- `FAILED` (irrecoverable) — infrastructure failure or similar non-recoverable condition.

**A new attempt is not reconciliation.** For a `commands` stage, a manual run or an
explicit re-run of the same head starts a new attempt that first moves the signal to
`RUNNING`, whatever it held, `PASS` included (`09-check-stages.md`, section 3). Reconciliation
and the sweep never replace a completed result.

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

The routing artifact emits this as an authenticated **Check Run** on the PR head commit.
The governance artifact reads it as part of merge eligibility evaluation and verifies
the publisher identity before trusting the route classification. On GitHub V1, commit
statuses are not an acceptable transport for RouteClassification (they are forgeable by
any `statuses: write` actor). See `05-governance-and-trust.md` for the provenance
requirement.

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
