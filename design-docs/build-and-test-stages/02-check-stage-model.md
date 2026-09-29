# 02 — Check Stage Model

## What a check stage is

A **check stage** is a stage whose result is decided by deterministic CI compute. It differs from
a **review stage** in how its result is decided:

| | Review stage (exists) | Check stage (new) |
|---|---|---|
| Work is done by | An AI reviewer | Build / test / scan tooling on a CI runner |
| Result is read from | Comments and review threads | The CI platform's own pass/fail result |
| Blocking means | All its threads are resolved | Its result is a success |
| Evidence kind | `REVIEW_RESULT`, `COMMENT_MATCH` | `WORKFLOW_RESULT`, `CHECK_RESULT` (defined in the neutral model, design doc 06, but **not yet implemented** by the GitHub runtime; delivery Phase 3 and 5) |

Both kinds produce the same `StageResultSignal` and are consumed by the same merge gate. The
merge gate does not care how a signal was produced (design doc 04, invariant R4).

## Two execution modes

| Mode | Who runs the work | Stagr's job | Typical use |
|---|---|---|---|
| **managed** (default) | A CI job that Stagr renders into the platform's native pipeline | Render the job; read its result; publish the signal | New repositories; simple build and test |
| **observed** | The team's existing CI (Jenkins, GitLab CI, SonarCloud, Azure Pipelines, ...) | Read one named result; publish the signal | Existing CI, external services, anything richer than commands |

`observed` is the neutrality and integration mechanism: it lets any CI or service participate
without Stagr modelling it. It also replaces the special-case "external gate" (design doc 05):
SonarCloud becomes an ordinary observed stage.

## Stage kinds

- Reuse `build` and `test` (already in the model).
- Every other optional check (integration, performance, SQL, SAST, DAST, scans) uses `custom`
  and are named with `name:`; a label has no behavior.
- Rationale: a kind must only change defaults, never semantics. A growing enum of kinds would
  force core changes for every new tool. (Decision D1 in 08.)

## Interpreting a native outcome

The platform reports a native outcome for the stage's job or check. The mapping is the same on
every platform:

| Native outcome | Stage result | Notes |
|---|---|---|
| success | `COMPLETED` + `PASS` | The **only** outcome that passes |
| failure (compile error, failing test) | `COMPLETED` + `FAILED` | The work ran and failed. Fixable by pushing a new head or re-running |
| timed out | `COMPLETED` + `FAILED` | Some platforms report a timeout only as failure or cancelled, so the reason is best effort; the conclusion is not |
| cancelled | `COMPLETED` + `FAILED` | Reason recorded as cancelled. Never treated as a pass |
| skipped, neutral, "not run" | Not a pass | **Never** treated as success, even if the platform's own required-check logic would accept it |
| never reported / not started | `PENDING` (or `RUNNING` once the trusted eligibility unit has started the work, 06) | Becomes a failure only through a documented timeout policy. The publish unit does not write `RUNNING` for check stages |
| Stagr could not read or verify the result | `FAILED` state | Infrastructure problem on Stagr's side; see below |

**Today's runtime is fail-open here.** For a stage without review evidence, the current GitHub
publish step treats only a job status of `failure` specially; cancelled, skipped or unset fall
through to a pass, and a cancelled run publishes nothing. Delivery Phase 3 inverts this to the
table above (only `success` passes, cancelled publishes `FAILED`). A job that was skipped because
the eligibility unit said "not eligible" is told apart from one skipped as a failure by the
eligibility unit's explicit output, not by the job status alone.

Two different "failed" meanings must stay distinct:

- **`COMPLETED` + `FAILED`** — the *work* failed (tests are red). This is normal, expected, and
  recoverable: a re-run or a new push can turn it green. Only a pull request event or an explicit
  re-run starts the work again; a wake-up never re-runs work that already has a result for the
  head (06).
- **`FAILED` state** — *Stagr* could not evaluate (API error, ambiguous evidence). It stays
  final for that head until the stage is re-run (as decided for design doc 06).

This distinction removes today's mismatch where governance reports a state-level failure as
"has not completed". A red test suite becomes `COMPLETED` + `FAILED`, which governance already
reports as "stage did not complete successfully".

## Re-runs, attempts and duplicates

CI platforms create a new attempt when a job is re-run. Rules:

1. Attempts of the **same job** (same verified producer, same pipeline / job attempt lineage) are
   ordered, and the **latest terminal attempt is authoritative**. A red re-run after a `PASS`
   turns the published result into `COMPLETED` + `FAILED`; a green re-run after a red one turns it
   into `PASS`. A re-run of the same trusted job is fresh evidence about the same head, and keeping
   an older `PASS` would leave the result stale by design (P5: every blocking stage must be green
   *now*). Only attempts that reached an outcome count; an attempt still running is not one.
   (Decision D9 in 08.)
2. Only a pull request event or an explicit re-run starts new work (06); a wake-up never re-runs
   work. The cost is that a flaky test can turn a green stage red on a re-run and block the merge
   until a later attempt is green. That is the correct fail-closed outcome; flaky-test policy
   belongs to the team's tests.
3. Two results with the same name that do **not** share an attempt lineage (for example a second
   job added by the pull request) are ambiguous and fail closed. "Latest wins" never applies
   across lineages, otherwise a later forged result could override a real red one.
4. Two different *producers* claiming the same stage is ambiguous and fails closed.

The adapter of each platform supplies the lineage (see 05, `attempt lineage`).

## State machine (per stage and head)

```
PENDING   (a dependency has not passed, or the platform has not started the work)
   |
RUNNING   (the platform reports the work queued or in progress)
   |
   +--> COMPLETED + PASS     until a later terminal attempt of the same lineage ends red
   +--> COMPLETED + FAILED   work failed; replaced by a later attempt (re-run) or a new head
   +--> COMPLETED + BLOCKED  (review stages only) findings open; re-evaluated
   +--> FAILED               Stagr could not evaluate; final until the stage is re-run
```

A new head starts every stage again at `PENDING`. An explicit re-run moves a stage from any
`COMPLETED` result, including `PASS`, back to `RUNNING` before the work starts (the lease, 06).

## Signal contents

The authoritative `StageResultSignal` payload is unchanged (schema version 1): stage id, head,
state, conclusion. Extra, optional, informational data (duration, counts of passed/failed tests,
a link to the platform's run page) goes in a separate human-readable field of the published
result and **never** affects the decision. The signal stays small and stable so any platform can
transport it.
