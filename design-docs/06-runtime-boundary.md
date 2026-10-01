# Stagr Neutral Core — Runtime Boundary and Rules Engine

**Status:** Target design. What is built today is in
[ARCHITECTURE.md, section 8](../docs/ARCHITECTURE.md#8-status--roadmap).

---

## Overview

Stagr runs only at render time. At run time the generated artifacts run inside the platform, and
they run the **rules engine**: one file that `stagr apply` writes into the repository (see "The
rules engine"). Stagr itself never runs as a service and is never called back, so "Stagr does not
run during pipeline execution" holds (#265, section 3).

This document is the home of the rules engine and of the run-time objects it reads and writes.

---

## What Stagr does and does not do

### At render time (`stagr apply`)

- Parse and validate `.agentic/config.yml`
- Expand profiles, normalize stages, derive `MergePolicy.blockingStageIds`
- Invoke BackendRenderer per agent stage → `ExecutionPlan`
- Invoke PlatformRenderer per stage → stage execution artifact
- Invoke PlatformRenderer for the pipeline → routing artifact + governance artifact
- Write the engine file and all artifacts to the target directory

### Never at run time

Stagr is never involved in:

- Listening to platform events
- Posting comments
- Calling model provider APIs
- Checking review status
- Inspecting diffs
- Merging a change: the platform's own merge mechanism merges (#265, section 2, decision 4)
- Any network call after `stagr apply` completes

The engine file does run at run time, inside the generated workflows, on the facts the platform
adapter passes to it. It is a generated artifact, not a Stagr service.

---

## The rules engine

The rules are defined once in core as an executable, neutral **reference engine** that uses only
the language's standard library, plus core-owned **conformance vectors**. A platform adapter
embeds the engine and supplies only a narrow platform port (#265, section 2, decision 2).

### What the engine decides

| Decision | Where the rule is written |
|---|---|
| Eligibility: may a run act on this change and revision? | "Eligibility" below |
| Start rule for managed stages | `09-check-stages.md`, section 5 |
| Dependency waiting | "Dependency rule" below |
| The stage result: state, conclusion and reason | "StageResultSignal" below |
| The conclusion of an agent stage from its evidence | "How a stage execution artifact determines conclusion" below |
| The result of a managed stage from its work outcome | `09-check-stages.md`, section 3 |
| Which observed result counts | `09-check-stages.md`, section 6 |
| The gate result | "Gate evaluation" below |

### The platform port: facts in, effects out

The engine never calls the platform. The adapter, which is the platform-specific part of each
generated workflow, collects the facts, runs the engine, and carries out the effects the engine
returns.

- **Facts:** the change (open or closed, ready or draft, same repository or fork, the author's
  role, the base it targets, merge conflict), its current revision, the event that woke the run,
  the stage results already published for the revision with their publisher identity, the route
  classification, evidence items and unresolved findings for the revision, and the work outcome of
  a managed stage.
- **Effects:** start a stage's work or invocation, write a stage result, write the gate result, or
  do nothing.

How the GitHub adapter supplies facts and carries out effects is in `08-github-codex-mapping.md`.

### Conformance vectors

The conformance vectors are a core-owned table of cases: facts in, expected decision and effects
out. They test the engine itself, and every adapter runs them through its own port, so no adapter
can drift from the rules. A rule and its vectors change in the same change.

### The engine file

`stagr apply` writes **one engine file** into the repository, next to the generated workflows, and
every generated workflow runs that file. Nothing is installed or fetched at run time, and the
engine is not pasted into each workflow. `stagr plan` fails if the file was edited or is out of
date (V-S16 in `07-validation.md`). Where the file lives is platform-specific
(`08-github-codex-mapping.md`). (#265, addendum, decision 21.)

### Eligibility

A run acts on a change only when every check holds. They run in this order, and the first failing
check decides. An ineligible run starts nothing and writes nothing.

1. The change is open and ready for review, its author's role and its source satisfy
   `TrustPolicy` (`05-governance-and-trust.md`), and the event's revision is still the change's
   current revision.
2. The stage applies to the change's route (`RoutingPolicy`, `05-governance-and-trust.md`).
3. For a wake-up, the stage's own result is not already final.
4. The dependency rule below allows the stage to start.

### Dependency rule

> **A dependent stage becomes eligible to start only when all of its declared dependencies have
> reached `COMPLETED` + `PASS` for the current revision.**

While any dependency is anything else (no result yet, `RUNNING`, `COMPLETED` + `BLOCKED`,
`COMPLETED` + `FAILED`, or state `FAILED`), the dependent **waits**: it is neither started nor
failed, and its own result is not set. A dependency's result can change: it turns `PASS` when
findings are resolved (`BLOCKED`) or when a later attempt or a new revision succeeds (`FAILED`). So
the dependent re-evaluates on each event that updates an upstream result, and starts on its own
once every upstream passes.

An upstream failure is never propagated. A dependent that failed for good because its upstream
failed once would stay failed after the upstream is fixed, and paid review stages would need a
manual restart. Nothing flows between stages; a stage that needs compiled output builds it again.

There is no conditional dependency ("run even if upstream failed") in V1. A stage with no
dependencies starts whenever its declared triggers fire.

Example:

```
build   (no dependencies)
review  (dependencies: [build])
```

- `build` starts on `CHANGE_UPDATED`.
- `review` starts only after `build` is `COMPLETED` + `PASS`.
- If `build` fails (a compile error, a failing test or an infrastructure error), `review` does not
  start and is not marked failed. It starts when `build` later passes.

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

Change content is untrusted: on a public repository anyone can post a comment that copies a
backend's selector text and the (public) revision. `producedBy` names the identity that
authors genuine evidence (mirroring `FindingScopeSpec.createdBy`, which does the same for
findings). The stage execution artifact must ignore any evidence item authored by another
identity.

- It is **required** for comment-based evidence (`REVIEW_RESULT`, `COMMENT_MATCH`). A
  PlatformRenderer must reject such a plan at render time when it is missing, rather than
  fall back to an unauthenticated match.
- The identity string is platform-defined; `08-github-codex-mapping.md` gives the GitHub form and
  how it is matched.

### EvidenceKind — semantic vocabulary

Evidence kinds are named for what they represent semantically, not for platform objects.
The PlatformRenderer maps each semantic kind to the appropriate platform API
(`08-github-codex-mapping.md` for GitHub).

| Value | Semantics |
|---|---|
| `REVIEW_RESULT` | A formal review object produced by a reviewer agent |
| `COMMENT_MATCH` | A comment on the change whose body satisfies the backend-defined selector expression (see compound selector convention below) |
| `CHECK_RESULT` | A named result authored by a named producer, with a pass/fail conclusion (an `observed` stage, `09-check-stages.md`) |
| `WORKFLOW_RESULT` | The platform's own outcome of the work unit a `commands` stage runs (`09-check-stages.md`) |

Using semantic vocabulary keeps EvidenceSpec portable: a `REVIEW_RESULT` may be a formatted
comment on one platform and a note on another. The renderer handles the mapping; the EvidenceSpec
stays neutral.

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

Specifies how to bind an evidence item to the correct revision, preventing a stale
evidence item from satisfying a check on a newer revision.

```
CorrelationSpec {
  revision:      boolean   // true = evidence must be correlated to the current revision
  revisionField: string    // which field within the evidence item carries the revision
                           // (backend-defined; e.g. "first code block in Code Review row")
}
```

When `revision: true`, the stage execution artifact must extract the revision from
`revisionField` and verify it matches the current revision before accepting the evidence as
valid.

### EvidenceSuccessCondition

| Value | Meaning | Example |
|---|---|---|
| `SUCCESS` | The operation passed with no failures. A failed result means the condition is NOT met. | Build and its tests passed |
| `COMPLETED` | The operation finished processing, regardless of findings. A review with 5 findings is COMPLETED. | Code review, security review |
| `MATCH_FOUND` | A specific pattern is present in the evidence. | A specific string in a comment body |

> **Key point:** `COMPLETED` means "the reviewer finished." It does NOT mean "the
> result satisfies the gate." Gate satisfaction is determined by
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
  selector: string                   // backend-defined; opaque to neutral contract
  scope:    FindingScopeSpec | null  // required for NO_OPEN_THREADS; null otherwise
}
```

### GateDispositionKind

| Value | Meaning | Example |
|---|---|---|
| `NO_OPEN_THREADS` | PASS if the platform reports zero unresolved review threads linked to this stage's invocation | A review with all threads resolved |
| `EXPLICIT_PASS_MARKER` | PASS if a specific completion marker is present in the backend's output | A comment containing `stagr:pass:<stageId>` |
| `ALWAYS_PASS` | PASS whenever the evidence condition is met (no separate gate check) | Build stages: success = PASS |

### FindingScopeSpec

`FindingScopeSpec` constrains which review threads count as "open threads linked to this
stage's invocation" for `NO_OPEN_THREADS`. Without it, the governance artifact would
count all unresolved threads on the change — including threads from other stages or
pre-existing discussions unrelated to this stage's run.

```
FindingScopeSpec {
  createdBy:             string         // only count threads from comments posted by this identity
  revision:              boolean        // true = only count threads linked to the current revision
  invocationCorrelation: string | null  // backend-defined; a per-invocation discriminator
                                        // the PlatformRenderer uses to distinguish this stage's
                                        // threads from those of another stage posted by the same
                                        // identity on the same revision
}
```

`invocationCorrelation` is necessary when two stages share the same bot identity and
revision. For example, when both `review` and `security` are posted by the same review bot on
the same revision, `createdBy + revision` alone cannot distinguish their threads.
`invocationCorrelation` provides the discriminator — a backend-defined, opaque string that
the PlatformRenderer uses to identify which platform objects (threads, review objects, or
other finding artifacts) belong to this specific stage's invocation.

The concrete binding of `invocationCorrelation` to a platform-observable primitive is a
BackendRenderer + PlatformRenderer implementation detail, not a neutral-contract concern. The
chosen binding must be reliably observable through the platform's review-thread API.
`08-github-codex-mapping.md` lists the candidate bindings on GitHub.

**V1 conservative fallback (shared-scope mode).** When a spike investigation demonstrates
that no reliable per-invocation binding is available for a given backend (the Codex finding
is recorded in `08-github-codex-mapping.md`), the BackendRenderer may use `NO_OPEN_THREADS`
with `invocationCorrelation=null` as a conservative V1 fallback. In this mode the gate is
scoped only by `createdBy + revision`: all unresolved threads from that bot identity on the
current revision must be resolved before any stage using this disposition passes. The
intentional consequence is **cross-stage blocking**: a finding from the REVIEW stage will keep
the SECURITY stage BLOCKED, and vice versa. This is fail-closed behavior, not a bug. The
BackendRenderer's module docstring must explicitly document this V1 shared-scope mode and the
spike finding that motivates it. The V1 fallback is not a general licence to omit
`invocationCorrelation`; it requires documented spike evidence that no reliable binding exists
for this specific backend.

**Gate-semantics constraint:** the V1 fallback is only valid when **all** stages that
share the bot identity and revision are configured with `BLOCKING` gate semantics. If
any co-sharing stage is configured `NON_BLOCKING` (advisory), the shared scope silently
causes that stage's unresolved findings to block every `BLOCKING` stage in the shared
scope, contradicting the user's explicit advisory-gate intent. In that situation the
BackendRenderer must not apply `NO_OPEN_THREADS` with shared scope to either the
advisory stage or any blocking stage sharing its identity; an alternative disposition
must be chosen instead.

When `invocationCorrelation` is null without a documented spike, `createdBy + revision` is
sufficient only when stages use distinct bot identities.

The BackendRenderer supplies both `EvidenceSpec` (when done?) and `GateDispositionSpec`
(PASS or BLOCKED?). The PlatformRenderer uses both to write the observation logic inside
the stage execution artifact.

---

## StageResultSignal — normalized runtime result

The `StageResultSignal` is the normalized result that stage execution artifacts emit and
the governance artifact consumes. It is the canonical bridge between raw backend
evidence and the gate. Every executor produces it (`09-check-stages.md`, section 1).

```
StageResultSignal {
  stageId:    string
  revision:   string
  state:      StageResultState
  conclusion: StageResultConclusion
  reason:     StageResultReason | null   // set only when the conclusion is FAILED
}
```

### StageResultState

| Value | Meaning |
|---|---|
| `PENDING` | Stage has not started, or its invocation has not been posted yet |
| `RUNNING` | Stage work or invocation is in flight |
| `COMPLETED` | Stage finished processing (findings may be present) |
| `FAILED` | Stagr could not evaluate the stage (infrastructure or API failure, ambiguous or unreadable evidence) |

### StageResultConclusion

| Value | Meaning |
|---|---|
| `PASS` | Stage completed and the result satisfies the gate (no blocking findings) |
| `BLOCKED` | Stage completed, but findings or conditions keep it from passing. For review stages: the review finished with unaddressed findings. |
| `FAILED` | Stage did not finish successfully. A dependency that has not passed never causes it: the dependent waits instead (dependency rule above). |
| `UNKNOWN` | No conclusion yet (`RUNNING`), or the signal is malformed or of an unknown version |

### StageResultReason

Why a stage failed, defined once here (#265, section 5). The decision record copies it, and the
platform adapter only displays it.

| Value | Meaning |
|---|---|
| `FAILURE` | The work or the evidence reported a failure |
| `TIMED_OUT` | The work reached its time limit |
| `CANCELLED` | The work was cancelled before it finished |
| `SKIPPED` | The work did not run |
| `UNREADABLE` | Stagr could not read or verify the outcome (state `FAILED`) |

How a platform tells a timeout from a cancel is platform-specific (`09-check-stages.md`,
section 8, capability 4).

### State machine per stage and revision

```
(no result)  =  PENDING
     |
  RUNNING  --> COMPLETED + PASS
     |    \--> COMPLETED + BLOCKED     findings open; may turn PASS without a new revision
     |     \-> COMPLETED + FAILED      the work failed; fixable by a re-run or a new revision
     |      \> FAILED                  Stagr could not evaluate; fixed by the next attempt
```

- A result that is not `COMPLETED` never passes: `RUNNING` carries conclusion `UNKNOWN`, and
  state `FAILED` carries conclusion `FAILED`.
- A new revision starts every stage over.
- For `commands` and `observed` stages, a new **attempt** on the same revision (a manual run or a
  re-run) moves the stage back to `RUNNING` first, whatever it held before, `PASS` included. The
  newest attempt decides; nothing is immutable (#265, section 5, decision 6). An agent stage keeps
  the result its evidence gives for the revision: its completion guard ("Idempotency") does not
  invoke the backend again while that evidence exists.
- Every result names its revision. A result for another revision never counts.

### Why COMPLETED ≠ PASS for review stages

A code review that produces 3 serious findings is `COMPLETED` (the reviewer finished
processing) but `BLOCKED` (the findings keep it from passing). The gate requires
`conclusion = PASS`, not `state = COMPLETED`. This separation prevents a completed
review with outstanding findings from satisfying a blocking gate.

### How a stage execution artifact determines conclusion

For agent stages (`REVIEW`, `SECURITY`, and `CUSTOM` with an agent executor), the evidence sets
the state and the stage's `GateDispositionSpec` sets the conclusion:

```
evidence of completion  →  state = COMPLETED
GateDispositionSpec     →  conclusion = PASS or BLOCKED
```

For `NO_OPEN_THREADS`, the disposition of the review and security stages, that means:

```
no unresolved findings linked to this stage  →  conclusion = PASS
unresolved findings linked to this stage     →  conclusion = BLOCKED
```

For `commands` and `observed` stages, the mapping is in `09-check-stages.md`, sections 3 and 6.

> **Note on "unresolved findings":** The stage execution artifact determines findings
> via its `EvidenceSpec`. For comment-based review backends, findings manifest as
> unresolved review threads. The stage execution artifact counts these and sets
> `conclusion = BLOCKED` when any are present. The governance artifact reads only the
> `StageResultSignal` — it does not count threads itself.

### Signal emission

The stage execution artifact emits the `StageResultSignal` to a well-known, per-stage
platform location declared in the `StageResultSpec` (`04-render-time-architecture.md`). The
governance artifact reads this location to evaluate the gate.

**Provenance requirement.** A `StageResultSignal` is a trust boundary: the governance
artifact uses it to decide the gate result. The signal must be published on a **result carrier
bound to the revision and written by the publisher identity**, a platform mechanism that carries
an authenticated publisher identity. The governance artifact must verify that identity against
`StageResultSpec.provenance.publisherIdentity` before trusting the result, and must reject a
signal from any other identity. A carrier that any actor with ordinary write access could forge is
never acceptable. The GitHub carrier is in `08-github-codex-mapping.md`.

---

## Gate evaluation

The governance artifact publishes **one gate result** for the change's current revision, on a
result carrier bound to the revision and written by the publisher identity, like a stage result
("Signal emission"). The platform's own merge mechanism requires that result, from that identity,
and performs the merge; Stagr never merges
(#265, section 2, decision 4). Whether a person must also approve is the approvals policy (#265,
section 2, decision 9, Plan B) and the platform's own merge settings (#265, addendum,
decision 23).

The gate result passes if and only if all of the following hold:

1. The change is open, ready for review, from the same repository, and targets the default
   branch as the platform reports it.
2. The author's role is in `TrustPolicy.trustedRoles` (`05-governance-and-trust.md`).
3. The change has no merge conflict.
4. A `RouteClassification` for the current revision is published by the routing artifact and is
   final (`05-governance-and-trust.md`).
5. For every stage in `RequiredStageIds`, a `StageResultSignal` for the current revision, from
   the publisher identity, is `COMPLETED` + `PASS`, where:

   ```
   RequiredStageIds = ApplicableStages(RouteClassification.route) ∩ MergePolicy.blockingStageIds
   ```

   A required stage that is missing, `PENDING`, `RUNNING`, `COMPLETED` + `BLOCKED`,
   `COMPLETED` + `FAILED` or in state `FAILED` keeps the gate from passing. Stages that do not
   apply to the route are excluded, and advisory stages are reported but never counted. Managed,
   observed and agent stages are treated identically.
6. When `MergePolicy.discussionPolicy.requireResolved` is true, zero open review discussions
   remain. This is read from the platform's discussion API, separately from `StageResultSignal`.

Any fact that is missing or unreadable means the gate result does not pass.

The decision-record condition ("a merge without a stored record fails the gate", #265, section 2,
decision 6) is designed in Plan B.

---

## Reconciliation model

After an invocation is posted and an initial `StageResultSignal` is emitted
(`state = RUNNING, conclusion = UNKNOWN`), the backend processes the request
asynchronously. The stage execution artifact must update the signal when the backend
completes — this is the **reconciliation loop**.

### Reconciliation triggers

Reconciliation events are platform-level wakeups that re-evaluate pending stage signals.
They are **not** declared `StageTrigger` values; they are a renderer-internal mechanism.

| Event | When it fires |
|---|---|
| A comment is created or edited on the change | The backend may have posted its result |
| A result on the revision completes | Covers result-based backends and upstream stages |
| Scheduled sweep | Periodic re-evaluation to recover from missed events |

The GitHub events are in `08-github-codex-mapping.md`.

On each reconciliation event, the stage execution artifact:

1. Resolves the change and its current revision
2. Checks the `EvidenceSpec` for the current revision — has the backend produced evidence?
3. If yes, evaluates the `GateDispositionSpec` — PASS or BLOCKED?
4. Emits an updated `StageResultSignal` (`state = COMPLETED, conclusion = PASS|BLOCKED`)

**Reconciliation termination rule.** A stage execution artifact stops re-evaluating a
signal only when it reaches a terminal state that cannot change without a new revision:

- `COMPLETED + PASS` — the gate condition is satisfied; re-evaluation adds no value.
- `FAILED` (irrecoverable) — infrastructure failure or similar non-recoverable condition.

**A new attempt is not reconciliation.** A new attempt of a `commands` or `observed` stage
replaces any result ("State machine" above). Reconciliation and the sweep never replace a
completed result.

**`COMPLETED + BLOCKED` is not terminal for reconciliation.** A BLOCKED conclusion means
the backend finished but found blocking issues. Those issues can be resolved (e.g.,
threads closed, findings addressed) without a new revision. The stage execution artifact
**must** continue re-evaluating on each reconciliation event to detect when the BLOCKED
condition clears and a PASS can be emitted.

**Recovery rule for expired in-flight markers.** When the reconciliation sweep runs and
all of the following hold, the artifact may post a fresh invocation:
1. A stage invocation was previously posted for the current revision (an in-flight marker
   exists for this revision).
2. No completion evidence exists for this revision (the backend has not responded).
3. The in-flight marker's expiry timestamp has passed.

In this case, the artifact treats the marker as absent and re-posts the invocation,
setting a new expiry. This recovers from backend outages or dropped invocations without
requiring a new revision.

### Why reconciliation is separate from StageTrigger

`StageTrigger` values (`CHANGE_OPENED`, `CHANGE_UPDATED`, `MANUAL`) declare when a stage's
*invocation* is requested. They are part of the neutral config and appear in
`NormalizedStage.triggers`. Reconciliation events are implementation details of how a
stage execution artifact *observes* backend completion after the invocation has been
posted. They are not visible in the neutral config.

---

## Idempotency

Stage execution artifacts that invoke backends with a comment command (`COMMENT_COMMAND`) must be
idempotent across two distinct failure modes:

### 1. Completion idempotency

Guard: "Has this stage already completed for this revision?"

Mechanism: EvidenceSpec-based check. Before posting an invocation, the stage execution
artifact evaluates the EvidenceSpec against the current revision. If evidence of
completion already exists and is bound to this revision, skip the invocation.

This is the steady-state guard (once done, stay done).

### 2. In-flight idempotency

Guard: "Has an invocation for this revision already been posted and is in flight?"

Mechanism: a durable per-revision, per-stage marker embedded in the invocation comment.
Format:

```
<!-- stagr:stage:<stageId>:<revision>:expires:<ISO8601-timestamp> -->
```

This marker is invisible to human readers and to the backend. Before posting an
invocation, the stage execution artifact checks whether a comment from the trusted
posting account already contains a still-valid marker for this stage and the current
revision. If yes, skip.

This guard covers the window between posting the invocation and the backend updating
its evidence (before the completion guard can pass).

### In-flight marker expiry (lease semantics)

An in-flight marker without expiry can permanently strand a change if the backend never
accepts the invocation (network failure, backend outage, malformed request). That is why the
marker carries an expiry timestamp. Before treating an existing marker as valid, the stage
execution artifact checks whether the expiry has passed. If expired, the marker is treated as
absent and a fresh invocation is posted. The expiry window is a per-backend configuration value
rendered into the stage execution artifact at render time (e.g., 30 minutes for a typical
review backend).

The two guards are complementary:
- Completion guard: steady state — already done, don't re-invoke
- In-flight marker: transient window — invocation posted, backend not yet responding
  (expires after the configured lease window; re-invocation happens on next eligible event)
