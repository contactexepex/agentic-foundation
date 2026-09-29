# 06 — Orchestration and Gating

This document says what runs when, what one stage triggers in another, and how the merge gate
decides. The merge gate rules themselves do **not change** (design doc
`05-governance-and-trust.md`, conditions 5 to 8): check stages plug into the rules that already
exist. The one gate-side change this plan needs is in this repository's own foundation gate (08, I10).

## The standard pipeline

```
   build ---+--> unit test ------------------+
            |                                |
            +--> code review, security ------+--> merge gate
                 review (their order:        |
                 sequential by default, D11)
   (optional, team-defined: integration, performance, SQL, SAST, DAST, scans)
```

- `build` runs first. Nothing else starts until the code compiles.
- `unit-test` and the two reviews then run. The plan does **not** change how the two reviews relate
  to each other (see below).
- Optional stages depend on whatever the team chooses (usually `build`).
- The merge gate needs every **blocking** stage to be `COMPLETED` + `PASS` for the current head
  and zero open review discussions.

Why reviews wait for `build`: an AI review costs money and a reviewer comment on code that does not
compile is noise. Why reviews do **not** wait for `unit-test`: it lengthens the critical path for
no safety gain, because the merge gate needs both anyway. (Decision D4 in 08.)

### Code review and security review order

This repository's contract (`AGENTS.md`, `CLAUDE.md`) says code review and security review run
**in sequence** in this repository's own automation, while `08-github-codex-mapping.md` plans them
as independent stages. This plan **chooses the generated default: sequential**. `stagr init` writes
`security` with `depends_on: [review]` (it already does), so the security review starts only after the
code review has completed clean and the two Codex requests never overlap (a concurrent pair is a
known error case of the reviewer backend). Reasons: it is the binding contract of this repository,
it is what `stagr init` generates today, and the extra latency is small next to the cost of a failed
security review. A repository can still remove the dependency explicitly. Delivery therefore has
nothing to invent; the owners confirm the choice as Decision D11, and if they choose independent
instead, only the generated default in I6 and the amended documents (below) change. Amending design
doc 02 (`standard` profile) and `08-github-codex-mapping.md` (removal of the review serialization)
is listed in 08.

Per design invariant R1 (no invented dependencies) every ordering is **written explicitly** into the
generated config by `stagr init` as `depends_on`; the renderer never adds an edge on its own.

## Dependencies express order, not data

`depends_on: [build]` means "start only after `build` passed for this head". Nothing flows between
stages: no artifacts, no variables. A stage that needs the compiled output rebuilds it or fetches
it through the team's own CI. This is deliberate (non-goals in 01). It keeps stages independent
and any platform able to run them.

## What a dependency does when the upstream is not green

| Upstream signal for the head | Effect on the dependent |
|---|---|
| `COMPLETED` + `PASS` | Start |
| anything else: missing, `PENDING`, `RUNNING`, `COMPLETED` + `BLOCKED`, `COMPLETED` + `FAILED`, state `FAILED` | **Wait.** The dependent does not start and is not marked failed |

This is an **amendment** to today's runtime (Decision D8), which turns an upstream
`conclusion == FAILED` or state `FAILED` into a terminal `FAILED` state for the dependent. That was
safe while upstream failures were rare. For check stages a red test is common, and even an
infrastructure error in `build` would leave the paid review stages stuck at a terminal `FAILED`
after `build` is fixed. With the amendment the dependent simply stays waiting and wakes up when the
upstream turns green. The merge gate blocks in the meantime because the upstream is not `PASS`. The
dependent's waiting reason is shown in its pending result text. (Delivery Phase 2.)

## Wake-ups and re-runs

Stages that wait need a nudge when their upstream changes. The mechanism exists and is unchanged:

- **Event wake-up:** an upstream result change wakes dependents (platform event).
- **Sweep:** a periodic, update-only pass that cannot start work or invoke a backend, re-evaluates waiting stages, so a missed
  event never strands a pull request (it cannot start a stage, as documented for design doc 08).
- **Reconcile:** a result that is not yet final and disagrees with the platform outcome is
  corrected (update only). Reconcile and the sweep never replace or revoke a completed result:
  they keep the early return on `COMPLETED` + `PASS` and on `FAILED`. Only the publish unit of a
  newer attempt can do that (see "The attempt token").

**A wake-up never runs work twice.** For a check stage:

- A wake-up may *start* a stage that has no result yet for the head (its dependency just turned
  green).
- A wake-up never starts a stage that already has a `RUNNING` or `COMPLETED` result for the head.
  Only a pull request event (opened, reopened, updated, ready for review) or an explicit re-run
  starts work again. Without this rule, unrelated check chatter would re-run tests and, worse,
  re-trigger paid stages in a loop.
- **The attempt token and the lineage.** A stage's *lineage* is its single result (on GitHub, the
  one Check Run) for one stage, one head and one verified producer. Every attempt that writes it
  carries an **attempt token**: the pair `(run id, run attempt)` of the pipeline run that
  contains the attempt. Tokens are compared as a pair, run id first and then attempt, so a later
  run, a re-run of the same run and a re-run of only its failed jobs are all ordered. Assumption to
  verify before I5: GitHub run ids increase over time. The token is stored in a separate,
  informational `lease` field of the result payload. It is not part of the consumer-facing
  signal (stage, head, state and conclusion are unchanged), and I5 verifies that the merge gate
  and other consumers ignore unknown payload fields (otherwise a compatible schema bump is needed).
  Rules:
  - Eligibility and publish may write the result only when their own token is **greater than or
    equal to** the stored one. A smaller token is a logged no-op: an older attempt that publishes
    late can never clobber a newer result (an older green after a newer red stays red).
  - **A run superseded by a newer run of the same head cannot publish over it.** Tokens compare run
    id first, so a re-run (even of only the failed jobs) of an older run has a smaller token than the
    newer run and is a logged no-op with a visible reason ("superseded by run N; re-run the latest
    run"). This is deliberate: the newer run is a complete validation of the same head and its result
    is genuine evidence; an operator who wants fresh evidence re-runs the latest run. The alternative,
    a platform-wide time-ordered sequence, needs an atomic counter the platform does not provide.
  - Publish never creates. If no Check Run exists it fails loudly and writes nothing.
  - Reconcile and the sweep have no attempt of their own. They only complete a non-final result for
    the attempt named in its `lease`, keep that token, and never replace or revoke a completed
    result.
  - A second result of the same name that is not this Check Run, or a result from another producer,
    is ambiguous and fails closed (02).
- **The lease.** After all its checks pass (04), the trusted eligibility unit writes `RUNNING`
  with its token before the work starts. The work unit never writes it: it has no credential
  (04, S1, S3). "Work started" comes only from the eligibility output. If eligibility was cancelled
  or evicted, no work started, and publish (which runs `always()`) writes nothing and reports
  why. Rules:
  - No result for the head yet: create `RUNNING`.
  - A `RUNNING` younger than the stage timeout plus the margin below is work in progress: skip,
    whatever the trigger. The log states the visible reason ("skipped: existing result").
  - The trigger is a **wake-up** and a `RUNNING` or `COMPLETED` result exists: skip, with the same
    logged reason.
  - The trigger is a **pull request event** and the existing result is `COMPLETED` + `FAILED`,
    state `FAILED`, or a `RUNNING` older than the stage timeout plus the margin (its runner
    died): replace it with a fresh `RUNNING`. An existing `COMPLETED` + `PASS` is left alone: the
    head is already green and the event asks for nothing new. A `PASS` is re-run only by an explicit
    action.
  - The trigger is an **explicit re-run** (a new attempt of the same pipeline run, or a manual
    trigger): replace **any** existing `COMPLETED` result, including `PASS`, and any stale `RUNNING`,
    with a fresh `RUNNING` **before** the work starts. Publish is the sole writer of the final
    result, so between the start of the re-run and its publish the stage is not `PASS` and the
    merge gate stays closed (fail closed, P5). The re-run then ends as the latest terminal attempt
    of its lineage and decides the result (02, D9): red publishes `COMPLETED` + `FAILED`, green
    publishes `PASS`.
  - **Stale margin.** The default margin is 15 minutes. A `RUNNING` is stale when its age exceeds
    the stage timeout plus 15 minutes. The age runs from the Check Run's server-side `started_at`
    to the platform's server time (taken from the API response), never from the runner's clock.
    To verify before I5: the API exposes both, and `started_at` is reset when the lease is
    replaced.
- **Who creates and who only updates, and the concurrency groups.** Exactly one unit creates the
  stage's Check Run: **eligibility**. Every other writer (publish, reconcile, sweep) only *updates*
  the existing one, so a duplicate Check Run cannot appear. The groups are chosen so that no queued
  job can evict a job that must run and produce a result (GitHub semantics, to verify: job-level
  groups, one running and one pending job per group, a newer pending job replaces an older one,
  `cancel-in-progress` false):
  - The eligibility job has its own job-level group per stage and pull request, with
    `cancel-in-progress` false. This serializes lease creation.
  - The publish job of a run that carried work has a group keyed by that workflow run id. Nothing
    else can share it, so a later-queued job can never replace a pending publisher. A run whose
    eligibility started no work writes nothing in publish.
  - Eligibility and publish never share a group. Otherwise a later wake-up's eligibility job would
    evict a queued publish job, the completed work would never be published and the stage would
    stay `RUNNING`.
  - **Known limitation (Decision D15).** A pending eligibility job can be replaced by a later one.
    That is harmless for wake-ups and pull request events, which read current state, but **not** for
    an explicit re-run: a pending re-run can be replaced by a later wake-up's eligibility job, which
    then skips because a result exists, and no work starts. This affects availability only. Safety
    is unchanged: the eviction never turns any result green. The result keeps its previous value (an
    earlier, genuinely earned `PASS` stays `PASS`; a `FAILED` stays `FAILED`), and the requested fresh
    validation simply does not happen. A queued re-run cannot invalidate the old result first,
    because the job that would do it is the one that was replaced. The
    platform shows the replaced run as cancelled, eligibility logs "skipped: existing result", and
    a human simply re-runs. A second eligibility group is deliberately not added, because it would
    break the single creator.
- **A publisher that dies.** If the publish job never writes (runner lost, credential outage), the
  stage stays `RUNNING` and the gate stays blocked. A `RUNNING` older than the stage timeout plus
  the 15-minute margin is treated as dead and is replaced by the next pull request event or
  explicit re-run. This recovery is **not automatic**: the sweep cannot start work or invoke a
  backend, so someone has to push or re-run.
- **Revoked prerequisites.** A dependent that already started keeps its own head-bound result; a
  re-run of its upstream does not cancel or reset it. The merge gate needs every blocking stage
  to be `PASS` *at the moment of merge*, so an upstream turned red or `RUNNING` by a re-run blocks
  the merge even though the dependent's result is unchanged.

**Observed stages** have their own wake-up need: the result comes from another system, so the
trigger is that system's completion event for the named result (filtered by name and producer), and
the sweep can only correct, not create. A missed event therefore leaves the stage `PENDING` until
the next pull request event or manual re-run; this limitation is documented and covered by
`observe.timeout_minutes`. Fork pull requests carry no pull request number in such events and are not
woken (the existing documented limitation).

## Triggers

Check stages use the existing neutral triggers: `pr_opened`, `pr_updated`, `manual`. A new head
resets every stage to `PENDING`. The work unit of a superseded head is cancelled (its own
concurrency group with cancel-in-progress), so a 360-minute run for an old head cannot block the
new head. Results are bound to their head (S9): the publish unit of a cancelled run updates only
the Check Run of its own, older head and can never overwrite the new head's result. The groups of
the trusted units are described under "The lease" above. Stages triggered by pushes to the default
branch (post-merge builds) are out of scope and a later design.

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
| Stagr's published result on failure | Failure | Signal payload says `FAILED`; the display value on the platform carrier is informational (non-failing) so it cannot trip a "all checks must pass" rule by accident (Decision D6) |
| Included in `blockingStageIds` | Yes | No |

Two limits of that softening, stated so nobody is surprised: (1) it applies only to the result
**Stagr publishes**; the platform's own job/check for the work unit still shows its real outcome, so
a team that marks every check required will still be blocked, and `continue-on-error` is **not**
used because it would destroy the attested outcome (S2); (2) the runtime has no notion of a gate
today, so the gate is passed to it as a render-time constant, like the other stage settings.

## Outputs of a stage

A check stage produces exactly one thing: its head-bound `StageResultSignal`, plus an optional
informational summary and link (02). It emits no artifacts and triggers nothing by itself.
"What a stage triggers" is expressed only through `depends_on`.

## One contract for external gates

Today `modules.sonar: true` adds an *external gate* that is **fail-open**: if the check is absent
it is ignored (design doc 05, "External gates (V1)"), and `stagr plan` / `stagr apply` do not
evaluate it at all (V-S15 warns). That contradicts P5 (fail closed) and P4 (verify the producer).
An observed stage (03) replaces it:

| | `modules.sonar` (V1) | Observed stage |
|---|---|---|
| Absent result | Tolerated (fail-open) | Not passed (fail closed) |
| Producer verified | No | Yes (`observe.producer`) |
| Head-bound | By check run on head | Yes |
| Appears in merge policy | Special case | Ordinary blocking or advisory stage |

Migration (Decision D5): keep `modules.sonar` working as a documented, deprecated alias for one
release; `stagr doctor` warns and prints the equivalent observed stage; a config that declares
both is an error. New code uses observed stages only. Rollback: remove the observed stage and
restore the alias line; nothing else changed.

## Re-runs, cancellation and timeouts

- **Re-run:** re-running the work unit creates a new attempt with a larger token. The latest
  terminal attempt decides the result: a red re-run after `PASS` turns it into `COMPLETED` +
  `FAILED`, a green one after red into `PASS` (02, D9). A full re-run runs eligibility again, which
  first replaces the old result with a fresh `RUNNING`, so the gate is closed for the whole re-run.
  Re-running **only the failed jobs** does not run eligibility again (it already succeeded), so no
  new `RUNNING` is written. It needs no special case: the work and publish jobs run as a newer
  attempt, and that publish updates the result because its token is larger. The stored result
  cannot be `PASS` in that case (a run with a failed job never published `PASS`), so the gate stays
  closed meanwhile.
- **Timeout:** a work unit that exceeds `run.timeout_minutes` ends as `COMPLETED` + `FAILED`
  (the reason may only say "failed or cancelled" on platforms that do not report timeouts
  distinctly). For observed stages the default is to wait; an optional `observe.timeout_minutes`
  converts a result that never appears into state `FAILED`.

## Non-normative: how this lands on today's GitHub runtime

Today one generated job holds eligibility, invocation and publish steps. For a managed check stage
the workflow becomes three jobs: `eligibility` (reuses the existing eligibility mode), a `work` job
that runs the configured commands with a read-only, non-persisted token and no secrets, and a
`publish` job that runs `always()` (not `!cancelled()`), reads the work job's result
(`needs.<job>.result`) as `WORKFLOW_RESULT` evidence, and updates the Check Run through the
publisher App. Reconcile and sweep stay update-only. Only the trusted eligibility job (the
`RUNNING` lease, the only creator of the Check Run) and the publish job (the final result) write
results. Their concurrency is job-level: `eligibility` has a group per stage and pull request
without cancelling, `publish` has a group keyed by the workflow run id, and `work` keeps its own
cancel-superseded group. The workflow-level group that the review-stage workflow uses today
(`stagr-<id>-<pull request number>`) is not applied to these jobs.

Runtime changes this needs (delivery Phases 2 and 3):

1. The dependency rule above (Phase 2).
2. The inverted, fail-closed outcome mapping (Phase 3, see 02).
3. The eligibility-written lease with the replace rules above (Phase 3).
4. **`PASS` is no longer untouchable, but only by publish.** Today `reconcile_pull_request` returns
   early with "signal is already completed and passed", and the runtime's write policy says a re-run
   of the execute job "never rewrites `pass`" (matching the alternative in D9). This is relaxed only
   for an explicit re-run or a newer attempt of the same lineage: eligibility replaces the result
   with `RUNNING`, and the **publish** job of a newer attempt may write `COMPLETED` + `FAILED` over a
   `PASS` (or `PASS` over `FAILED`). Reconcile and the sweep keep the early return on completed
   results and never turn a `PASS` red. Wake-ups start no work on a head that has a result. The
   ambiguity rules for other Check Runs or producers are unchanged.
5. **The attempt token** in a separate `lease` payload field, written by eligibility and publish
   and compared as in "The attempt token and the lineage" above. Publish, reconcile and sweep update
   only with a token greater than or equal to the stored one. I5 verifies that consumers ignore
   the extra field.
6. **Publish becomes update-only for managed check stages** (today, in publish mode, the runtime
   may still create the Check Run). Creating moves to the eligibility job alone, together with the
   job-level groups above. Review stages keep their current behaviour.
7. **Reconcile and sweep jobs for managed check stages.** They are rendered today only for a stage
   with asynchronous evidence (`has_asynchronous_evidence`), and a managed check stage has none.
   This plan does not require them. If they are wanted for check stages (for example to complete a `RUNNING` whose publish job died),
   the renderer must add them, with the App token they already use, and the runtime must read the
   platform outcome of the attempt named in the lease. Without them, recovery is only by a new pull
   request event or explicit re-run (see "A publisher that dies").
