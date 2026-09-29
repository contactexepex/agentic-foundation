# 06 — Orchestration and Gating

This document says what runs when, what one stage triggers in another, and how the merge gate
decides. The merge gate itself does **not change** (design doc `05-governance-and-trust.md`,
conditions 5 to 8): check stages plug into the rules that already exist.

## The standard pipeline

```
                     +--> code review ------+
   build ---+        |                      |
            +--------+--> security review --+--> merge gate
            |                               |
            +--> unit test -----------------+
   (optional, team-defined: integration, performance, SQL, SAST, DAST, scans)
```

- `build` runs first. Nothing else starts until the code compiles.
- `unit-test`, `code review` and `security review` then run **in parallel**.
- Optional stages depend on whatever the team chooses (usually `build`).
- The merge gate needs every **blocking** stage to be `COMPLETED` + `PASS` for the current head
  and zero open review discussions.

Why reviews wait for `build`: an AI review costs money and a reviewer comment on code that does not
compile is noise. Why reviews do **not** wait for `unit-test`: it lengthens the critical path for
no safety gain, because the merge gate needs both anyway. (Decision D4 in 08: recommended default;
a team can rewire it.)

Per design invariant R1 (no invented dependencies) the ordering is **written explicitly** into the
generated config by `stagr init` as `depends_on`; the renderer never adds an edge on its own.

## Dependencies express order, not data

`depends_on: [build]` means "start only after `build` passed for this head". Nothing flows between
stages: no artifacts, no variables. A stage that needs the compiled output rebuilds it or fetches
it through the team's own CI. This is deliberate (non-goals in 01). It keeps stages independent
and any platform able to run them.

## What a dependency does when the upstream is red

| Upstream signal for the head | Effect on the dependent |
|---|---|
| `COMPLETED` + `PASS` | Start |
| missing, `PENDING`, `RUNNING` | Wait (not started, not failed) |
| `COMPLETED` + `BLOCKED` or `COMPLETED` + `FAILED` | **Wait** (recoverable: a re-run or a new push can fix it) |
| state `FAILED` (Stagr could not evaluate) | Dependent becomes state `FAILED` ("dependency failed"), terminal until re-run |

The third row is an **amendment** to today's runtime, which turns any upstream
`conclusion == FAILED` into a terminal `FAILED` state for the dependent. That was safe while
`COMPLETED` + `FAILED` was rare. For check stages it is common (a red test), and it would leave a
review stuck at `FAILED` even after the test is fixed and re-run. With the amendment, the
dependent simply stays waiting, and wakes up when the upstream turns green. The merge gate blocks
in the meantime because the failing stage is not `PASS`. (Delivery Phase 2 changes the rule, with
tests and a migration note.)

## Wake-ups

Stages that wait need a nudge when their upstream changes. The mechanism already exists and is
unchanged:

- **Event wake-up:** an upstream result change wakes dependents (platform event).
- **Sweep:** a periodic, credential-free pass re-evaluates waiting stages, so a missed event
  never strands a pull request.
- **Reconcile:** a result that disagrees with the platform outcome is corrected (update only).

The neutral requirement (per platform in 05): *some* mechanism must re-evaluate a waiting stage
after its upstream changes, and a missed nudge must be recoverable.

## Triggers

Check stages use the existing neutral triggers: `pr_opened`, `pr_updated`, `manual`. A new head
resets every stage to `PENDING` and cancels the superseded run where the platform supports it.
Stages triggered by pushes to the default branch (post-merge builds) are out of scope here and
are a later design.

## Routing (fast path)

A stage runs on a route (`FAST` or `NORMAL`) only if the route lists it (design doc 05,
RoutingPolicy). Check stages follow the same rule with no exceptions: a docs-only fast path may
exclude `unit-test` **only if the team lists the stages for that route explicitly**. The
toolkit never assumes docs-only changes skip a build. In this repository the fast path is disabled,
so every stage applies to every pull request.

## Advisory versus blocking, end to end

| | Blocking | Advisory |
|---|---|---|
| Must complete before merge | Yes | No |
| Must be `PASS` | Yes | No |
| Review comments must be resolved | Yes (merge gate condition 8) | No |
| Publishes a result | Yes | Yes |
| Native result shown | Real outcome (success or failure) | Real outcome, but a failure is shown as **neutral** so it cannot trip "all checks must pass" rules by accident |
| Included in `blockingStageIds` | Yes | No |

The neutral `StageResultSignal` still says `FAILED` for a red advisory stage; only the platform
carrier's display value is softened, and the signal payload remains the authority (design doc 06).
An advisory stage that has not finished never holds the gate.

## Outputs of a stage

A check stage produces exactly one thing: its head-bound `StageResultSignal`, plus an optional
informational summary and link (02). It emits no artifacts and triggers nothing by itself.
"What a stage triggers" is expressed only through `depends_on`.

## One contract for external gates

Today `modules.sonar: true` adds an *external gate* that is **fail-open**: if the check is absent
it is ignored (design doc 05, "External gates (V1)"). That contradicts P5 (fail closed) and P4
(verify the producer). An observed stage (03) replaces it:

| | `modules.sonar` (V1) | Observed stage |
|---|---|---|
| Absent result | Tolerated (fail-open) | Not passed (fail closed) |
| Producer verified | No | Yes (`observe.producer`) |
| Head-bound | By check run on head | Yes |
| Appears in merge policy | Special case | Ordinary blocking or advisory stage |

Migration (Decision D5): keep `modules.sonar` working as a documented, deprecated alias for one
release; `stagr doctor` warns and prints the equivalent observed stage; a config that declares
both is an error. New code uses observed stages only.

## Re-runs, cancellation and timeouts

- **Re-run:** re-running the execute unit creates a new attempt; the latest attempt is
  authoritative (02).
- **Superseded run:** when a new head arrives, an older run may be cancelled. Its outcome is
  published only if its head is still current (S9), so a late cancellation can never overwrite the
  new head's result.
- **Timeout:** an execute unit that exceeds `run.timeout_minutes` ends as `COMPLETED` + `FAILED`
  with reason "timeout". For observed stages the default is to wait; an optional
  `observe.timeout_minutes` converts a result that never appears into state `FAILED`.

## Non-normative: how this lands on today's GitHub runtime

The existing generated `stage-<id>.yml` and its Python runtime already provide eligibility,
publish, reconcile and sweep. For a managed check stage:

- `eligibility` and `publish` are reused unchanged in shape.
- The AI-backend `invoke` step is replaced by an unprivileged `execute` job that runs the
  configured commands with a read-only token and no secrets.
- `publish` reads the execute job's outcome (`needs.<job>.result`) as `WORKFLOW_RESULT` evidence
  and writes the Check Run through the publisher App. Reconcile and sweep stay update-only.
- The dependency rule above is the one runtime change (Phase 2).
