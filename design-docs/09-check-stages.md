# Stagr Neutral Core — Check Stages (build and other CI results)

**Status:** Target design. What is built today is in
[ARCHITECTURE.md, section 8](../docs/ARCHITECTURE.md#8-status--roadmap).

---

## Premise

Stagr is pre-release and has **zero consumers**. This design describes the target and nothing
else: no migration path, no compatibility layer, no deprecated alias, no legacy behavior kept
for its own sake. Existing schemas, workflows and runtime behavior are changed or removed
wherever the target needs it.

Every rule below is stated **once**. Other sections refer to it; they do not restate it.

## What we are building

The `standard` profile (`02-canonical-stage-model.md`) is built from these stages; the gate rule
is in `06-runtime-boundary.md`, "Gate evaluation":

| Stage | Meaning |
|---|---|
| `build` | The code builds and its unit tests pass |
| `review` | Code review finished, all comments resolved |
| `security` | Security review finished, all comments resolved |

A team can add more (integration tests, SAST, dependency scans) and can plug in checks its own
CI already runs. Stagr stays a control plane (Charter §2): it writes the wiring, the platform
runs the work.

---

## 1. Stage model

Every stage has an **executor** that says who does the work:

| Executor | Who does the work | Fields |
|---|---|---|
| `agent` | An AI backend (today's review and security stages) | `provider`, `backend`, `model`, `skill` |
| `commands` | A CI job that Stagr renders (**managed**) | `commands`, `timeoutMinutes` |
| `observed` | The team's own CI or an external service; Stagr only reads the result | `check`, `producer` (author identity) |

```
NormalizedStage { id, kind, gate, triggers, dependencies, executor }
```

- `BUILD` is never an `agent` stage. `REVIEW` and `SECURITY` are always `agent`. `CUSTOM` may
  use any executor. The stage kinds are in `02-canonical-stage-model.md`.
- A `commands` or `observed` stage has no provider, backend, model or skill.
- All executors produce the same `StageResultSignal` (`06-runtime-boundary.md`) and are consumed by
  the same gate.
- Rendering: an `agent` stage goes through the BackendRenderer registry as today. A `commands`
  or `observed` stage goes through a built-in planner (no registry lookup) that returns an
  `ExecutionPlan` with a new `InvocationKind` (`RUN_COMMANDS` or `READ_RESULT`), the
  `ALWAYS_PASS` gate disposition, `WORKFLOW_RESULT` or `CHECK_RESULT` evidence, and **no
  required secrets**.
- Gate default: **`BLOCKING` for every kind**, `CUSTOM` included. A stage is advisory only when
  it says `gate: advisory` (which normalizes to `NON_BLOCKING`; config keys are mapped to the
  model in `01-neutral-config-contract.md`). `REVIEW` and `SECURITY` stages must be blocking, because their findings share one
  thread scope (`06-runtime-boundary.md`, "Gate-semantics constraint"); advisory therefore
  exists only for `commands` and `observed` stages.

## 2. Config

The common repository writes a profile and a `build:` block:

```yaml
version: 2
profile: standard            # see 02-canonical-stage-model.md
platform: { scm: github, publisher: { app_id: 123456 } }
build:
  preset: maven              # python | maven | gradle | node | go | rust | dotnet | custom
  # commands:                # optional overrides; a preset fills every key it can
  #   test: mvn -B verify
```

`build:` is the **only** home of the commands of the `build` stage. The stage runs
`install`, `build`, `lint`, `typecheck` and `test` in this order; the first failing command fails
the stage (#265, section 5).

`build.commands.build` (compile or package) has a default per preset:

| Preset | `build.commands.build` default |
|---|---|
| `python` | none (no compile step; `install`, `lint` and `typecheck` still run) |
| `maven` | `mvn -B -q -DskipTests package` |
| `gradle` | `./gradlew assemble` |
| `node` | `npm run build --if-present` |
| `go` | `go build ./...` |
| `rust` | `cargo build` |
| `dotnet` | `dotnet build --no-restore` |
| `custom` | none; the operator sets every command |

An empty command is skipped. Each preset also supplies its `install`, `lint`, `typecheck` and `test`
defaults (work item A).

Extra check stages use `stages:`:

```yaml
stages:
  - id: integration-test
    type: custom
    depends_on: [build]
    commands: ["./scripts/integration.sh"]
    timeout_minutes: 30          # 1..360, default 30
    gate: advisory               # optional; default blocking
  - id: analysis
    type: custom
    observe: { check: "Code Analysis", producer: 12526 }   # identity of the tool (rule 3)
```

An extra stage that omits `triggers` runs on `change_opened` and `change_updated`. For an observed
stage those are its change runs; its other run causes are renderer-internal wake-ups
(section 6), not triggers.

Validation rules (static, fail `stagr plan` and `stagr apply`):

1. A stage has `commands` or `observe`, never both. `commands` is allowed only on `custom`
   stages (the baseline stages take theirs from `build:`); a `build` stage that is
   built by the team's own CI declares `observe` instead.
2. `commands` has at least one entry. A blocking or advisory stage with nothing to run is an
   error, never a silent no-op. A repository with nothing to build sets `enabled: false` on
   `build` and clears the reviews' `depends_on` (a stage cannot depend on a disabled stage,
   `02-canonical-stage-model.md`).
3. `observe.check` and `observe.producer` are both required. An observed stage has no
   `depends_on` (nothing of it is started; stages that depend on it are fine).
   `observe.producer` is the platform's **immutable identity of the author** of the result,
   never a display name or login (those are mutable and forgeable); a number or a quoted string
   is accepted and normalized to a string. The platform renderer rejects any other form, and
   rejects the platform's own CI identity: every workflow in the repository shares it, so a
   change could add a job with the observed name and satisfy the stage. The team's own CI on the
   platform is a `commands` stage instead. The form each platform accepts is in section 8,
   capability 9.
4. There is **no `secrets` key**: a managed stage never receives a secret (section 4, E2). A
   check that needs a credential runs in a tool with its own author identity (for example
   SonarCloud, or another CI that reports through its own App) and is `observed`.
5. Unknown keys are rejected (`01-neutral-config-contract.md`). `build` is a recognized Stagr key.

There are no `matrix`, `services`, `cache`, `container`, `env`, `if`, `retries` or artifact
keys. That is CI-system territory; a team that needs it uses `observed` (Charter §5, §6).

---

## 3. Result model

One table decides every managed result. The **work outcome** is what the platform itself
reports for the work job (section 4).

| Work outcome | Signal (`state` + `conclusion`, reason) |
|---|---|
| success | `COMPLETED` + `PASS` — the **only** outcome that passes |
| failure, timed out, cancelled, skipped | `COMPLETED` + `FAILED`, reason `FAILURE`, `TIMED_OUT`, `CANCELLED` or `SKIPPED` |
| Stagr could not read or verify the outcome | state `FAILED` + conclusion `FAILED`, reason `UNREADABLE` |

The signal, its state machine, the reasons and "newest attempt wins" are defined in
`06-runtime-boundary.md`, "StageResultSignal". For managed stages:

- Only the publish unit writes a terminal result. Only the eligibility unit writes `RUNNING`.
  The work unit writes nothing.
- Between the start of a new attempt and the moment its `RUNNING` is written (event delivery,
  normally seconds) the previous result is still visible; a missed event lasts until the next
  scheduled run. This short window is accepted: the previous result is genuine evidence about
  the same revision, and it applies equally to managed and observed stages.
- Optional informational data (duration, link to the run page) may sit beside the signal and
  never affects the decision.

## 4. Execution and trust

A managed stage renders **three units in one run**, in order:

1. **Eligibility** (trusted): runs the engine's eligibility checks (`06-runtime-boundary.md`,
   "Eligibility") and the start rule (section 5). Only then does it write `RUNNING` and let the
   work start.
2. **Work** (untrusted): checks out the exact revision and runs the commands.
3. **Publish** (trusted, runs even if the work failed or was cancelled): reads the work
   outcome, applies the table in section 3 and updates the result. If eligibility did not start
   the work, publish writes nothing.

Rules (each is a test):

| # | Rule |
|---|---|
| E1 | The work unit never receives the publisher credential. Eligibility and publish hold it and never check out or run change content. |
| E2 | The work unit receives **no secrets**. Its repository token is read-only and is not stored in the checked-out workspace. |
| E3 | The result is the platform's own outcome of the work unit — never an output, artifact, log line, comment or status the executed code could write. |
| E4 | The job definition comes from the trusted base branch, so a change cannot rewrite the job that judges it in the same run. A change to `.agentic/**` or to a generated workflow therefore takes effect only after it is merged. |
| E5 | Managed stages run only for authors in `TrustPolicy.trustedRoles` on same-repository branches. Changes from forks never run them and therefore never pass them. |
| E6 | The work unit has a timeout, runs on an ephemeral runner, renders no cache steps, and receives commands as data (environment variable or file), never spliced into script text. |
| E7 | Every third-party action or image Stagr renders is pinned to an immutable identifier. |

Residual risks, stated openly: malicious code inside the change is caught by code and security
review, not by Stagr; the platform's cache service token is reachable from any job that runs
from the trusted base's definition (section 8, capability 3), which is accepted for trusted
same-repository authors because no cache step is rendered; runner isolation flaws belong to the
platform.

## 5. Running order

**Dependencies.** `depends_on` follows the engine's dependency rule (`06-runtime-boundary.md`,
"Dependency rule"): a dependent waits until every dependency passes and is never failed by one.

**Start rule** (managed stages, evaluated by eligibility):

| What woke the run | Action |
|---|---|
| Change opened, reopened, ready for review or given a new revision; manual run; explicit re-run | Dependencies `PASS`: reset to `RUNNING` and start the work. Otherwise wait |
| An upstream stage's result changed (wake-up) | Dependencies `PASS` **and** no result exists for this revision: start. Otherwise do nothing |

So unrelated check chatter never re-runs finished work, and an explicit action always does.

**Concurrency.** Runs of one stage for one change never overlap, and a new revision cancels the
older revision's work; nothing else cancels a run. Consequences, all following from that one rule:

- Writes to one result are ordered in time, so "newest attempt wins" needs no counter, lease or
  token.
- A `RUNNING` that eligibility finds when it starts belongs to a run that already ended, so it is
  simply replaced. A publisher that died leaves `RUNNING`; the gate stays closed until the next
  change event, manual run or re-run replaces it.
- Safety never depends on concurrency behavior. It comes from revision-bound results and "only
  `success` passes". Concurrency affects only cost and availability.

Known limit: a queued manual run can be replaced by a later queued run. The platform shows it as
cancelled and the operator runs it again. Nothing ever turns green because of it.

## 6. Observed stages

An observed stage has no work unit. One trusted job reads the **newest** result named
`observe.check` for the current revision, whose authenticated author identity equals
`observe.producer`, and publishes the signal. The newest result is the one the platform created
last (section 8, capability 9); it is chosen by creation, not by start time, because a queued
result has not started yet. When the producer has run more than once on the same revision, the
newest evidence wins, as for managed stages (`06-runtime-boundary.md`, "StageResultSignal").

| Result of the producer | Signal |
|---|---|
| success | `COMPLETED` + `PASS` |
| completed, not success (failure, cancelled, skipped, neutral, timed out) | `COMPLETED` + `FAILED`, with the matching reason (a neutral result counts as `FAILURE`) |
| not present | no result |
| queued or still running | `RUNNING` |

Results with the same name from any other author identity are ignored, so nobody else can
satisfy the stage by creating a check with that name. The job runs on change events, when
the producer's result is **created, re-requested or completed**, and on a schedule. The tool must
post its result on the change: a tool that never posts one is not supported as an observed
stage, and its stage stays without a result and blocks. Waking when
the producer *starts* matters: a producer that re-runs a check after an earlier success flips
the signal from `PASS` to `RUNNING` at the start of the re-run, not at its end. Because the job
only reads and derives, running it again is always safe, so a missed event is corrected by the
next run. Safety never depends on a wake-up: a missed one only lengthens the window that
section 3 accepts. SonarCloud is an observed stage
like any other, and an absent result blocks.

## 7. Gate

No new rule: check stages count in the gate exactly like agent stages (`06-runtime-boundary.md`,
"Gate evaluation").

## 8. Platform neutrality

The neutral parts above name no platform. A platform can host a managed stage only if it
provides these capabilities; a renderer that cannot provide one refuses to render the stage.

| # | Capability | GitHub |
|---|---|---|
| 1 | Ephemeral runners | GitHub-hosted runners (self-hosted only if ephemeral) |
| 2 | Work unit without credentials; read-only, non-stored repository token | separate job with `permissions: contents: read`, checkout with `persist-credentials: false`, no App token step |
| 3 | Job definition from the trusted base | `pull_request_target` |
| 4 | Platform-attested outcome of the work unit, readable by publish | `needs.<work job>.result`. GitHub reports a timeout as `cancelled` (section 9, fact 2), so publish records the reason "timed out" when the work job's run time, read from the jobs API with publish's `actions: read` permission, reached its `timeout-minutes`. Known limit: a cancel requested shortly before the limit can be recorded as "timed out"; both fail the stage the same way |
| 5 | Runs of one stage per change never overlap; a new revision cancels older-revision work | one concurrency group per stage and pull request; `cancel-in-progress` only on `synchronize` |
| 6 | Result carrier authored by the publisher identity and bound to a revision | Check Run written by the Stagr App |
| 7 | Wake-up when another stage's result changes | `check_run` / `check_suite` completed |
| 8 | Per-job timeout | `timeout-minutes` |
| 9 | Observed stages only: list results by name and authenticated author identity for a revision, and wake when such a result is created, re-requested or completed | Check Runs API: every result for the head with that name, matched on `.app.id`; the highest check-run id wins (`filter=latest` is not enough, section 9, fact 4); `check_run` created, rerequested, completed. GitHub Actions (App id 15368) is rejected as a producer (section 2, rule 3) |

Other platforms (GitLab, Azure DevOps, Bitbucket, Jenkins) are added later as one column of
this table each, checked against that vendor's documentation at that time. None is claimed now.

## 9. Verification before code

The GitHub column above rests on behavior confirmed on real GitHub before the managed workflow
is built (item S below). Throwaway workflows ran on 2026-09-30 in the test repository
`exepex/spring-angular-book-management`. Issue #249 lists every run.

| # | Fact | Result |
|---|---|---|
| 1 | A manual run and a re-run wait in the same concurrency group as ordinary runs (no overlap) | **Verified.** A manual run started after the pull-request run ended ([run](https://github.com/exepex/spring-angular-book-management/actions/runs/36748955501)), and a re-run started after a manual run ended ([run](https://github.com/exepex/spring-angular-book-management/actions/runs/36748953700), attempt 2) |
| 2 | `needs.<work job>.result` reports failure, timeout, cancelled and skipped, and a publish job with `always()` still runs after each | **Corrected.** Publish runs after each. GitHub reports `success`, `failure`, `cancelled` and `skipped`, but a **timeout is reported as `cancelled`**, in `needs.<work job>.result` and in the check-run conclusion alike ([timeout](https://github.com/exepex/spring-angular-book-management/actions/runs/36748905937), [cancelled](https://github.com/exepex/spring-angular-book-management/actions/runs/36748910303)). Publish therefore tells them apart by run time (section 8, capability 4) |
| 3 | A `pull_request_target` job can check out the head SHA with a read-only, non-stored token and no App token | **Verified.** The head matched, no credential stayed in `.git`, and a write with the token was refused with HTTP 403 ([run](https://github.com/exepex/spring-angular-book-management/actions/runs/36748953700)) |
| 4 | The Check Runs API with `filter=latest` returns one result per name and author after a re-run | **Corrected.** It holds for a re-run inside one workflow run ([run](https://github.com/exepex/spring-angular-book-management/actions/runs/36749923387)). Separate runs on the same head each stay "latest", because `filter=latest` works per check suite ([run](https://github.com/exepex/spring-angular-book-management/actions/runs/36749380522)). Stagr therefore lists every result and takes the newest by creation (section 6) |
| 5 | A `check_run` created, rerequested or completed event from a foreign producer starts a workflow for the pull request | **Verified for created and completed**, from SonarCloud and CodeQL ([created](https://github.com/exepex/spring-angular-book-management/actions/runs/36749001079), [completed](https://github.com/exepex/spring-angular-book-management/actions/runs/36749059157)). Rerequested was not exercised; the design does not depend on it (section 6) |
| 6 | `cancel-in-progress` accepts an expression | **Verified.** A push cancelled the older head's work; a manual run and a re-run cancelled nothing ([cancelled run](https://github.com/exepex/spring-angular-book-management/actions/runs/36749940333)) |
| 7 | A result written by the Stagr App starts a `check_run` workflow (section 8, capability 7) | **Verified** on 2026-10-01. Both created and completed started the workflow within about three seconds, naming the pull request ([write](https://github.com/exepex/spring-angular-book-management/actions/runs/36836277797), [created](https://github.com/exepex/spring-angular-book-management/actions/runs/36836298185), [completed](https://github.com/exepex/spring-angular-book-management/actions/runs/36836298452)). The App needs the Checks read and write permission to write results |

Also observed:

- A cancel, a timeout and a push-cancel each took about 75 to 90 seconds to stop the job. The
  next run in the group waits during that time, so runs still never overlap.
- Results created by GitHub Actions itself (App id 15368) never started a `check_run` workflow:
  about 20 such results during the test, against 19 wake-ups that all came from SonarCloud and
  CodeQL. GitHub Actions is not an observed producer anyway (section 2, rule 3).
- Check-run ids rose with creation time throughout the test, which section 6 relies on to pick
  the newest result.

If a fact turns out false, this document is corrected first, then the code.

## 10. Baseline profile

What `standard` and `minimal` expand to is in `02-canonical-stage-model.md`, "V1 shipped
profiles". This section gives the reasons for the order of `standard`.

**Reviews wait for `build`** because an AI review of code that does not compile or whose tests
fail is noise and costs money (#265, section 5).

**Security waits for the code review** because this repository's contract (`AGENTS.md`, "Git and
pull-request rules") says the two reviews run in sequence. Whether the review backend really fails on a
concurrent pair is unverified (`07-validation.md`), so this is a default, not a proof; a
repository may remove the dependency.

---

## 11. Work items

Each item ships its own user documentation (`CONFIGURATION.md`, `ARCHITECTURE.md`, `CLI.md`).
Order: S first, then A; B, D, E and F after A; C after A, B and S; G after A, C and E; H last.
Outside this design: `stagr plan` and `stagr apply` on the neutral pipeline are delivered
(`stagr/cli/render_pipeline.py`); `init` and `doctor` on the neutral pipeline are delivered
separately, and G needs the latter.

**S. Verify the GitHub behavior of section 9.**
- Done when: each of the seven facts is marked verified or corrected in section 9, with the
  workflow run that showed it.
- Test: the throwaway workflow and its run links; no product code.

**A. Stage model, config and schema.**
- Done when: `NormalizedStage` has an executor; a `commands` or `observed` stage needs no
  provider; the schema adds `build` to `type`, `build.commands.build` with preset defaults,
  `commands`, `timeout_minutes`, `observe.check`, `observe.producer`; rules 1–5 of section 2
  hold; the preset table of section 2 is implemented and mirrored in the preset docs; `triggers`
  defaults to `change_opened` and `change_updated` for `commands` and `observed` stages; the gate defaults to blocking for every kind; secret values are never echoed in errors.
- Test: `validate_config.py` and the neutral-core tests, one accepting and one rejecting case per
  rule; removing any rule makes a test fail.

**B. Outcome mapping.**
- Done when: one pure function maps the work outcome to a signal exactly as section 3; only
  `success` passes (the runtime's current job-status mapping, which special-cases only `failure`,
  is replaced); the function names no platform.
- Test: a vector table with success, failure, timed out, cancelled, skipped and unreadable, and a
  mutation check per row.

**C. Managed check stage on GitHub.**
- Done when: a `commands` stage renders eligibility, work and publish jobs; rules E1–E7 hold in
  the rendered file; start rule, concurrency and `RUNNING` handling follow section 5; publish
  writes only for a stage whose eligibility started the work, and only for the revision the run
  started for; forks, drafts and untrusted authors start nothing; hostile commands and branch
  names stay inert.
- Test: render-structure tests per rule; behavioral tests with the fake CLI for success, failure,
  timeout, cancelled, re-run after `FAILED`, re-run after `PASS` (red, then green), moved revision,
  wake-up with an existing result, and a stale `RUNNING` replaced by a change event;
  `actionlint` clean; interop with the real governance workflow.

**D. Dependency rule.**
- Done when: every non-`PASS` upstream makes a dependent wait, for every stage kind, and a
  dependent starts when the upstream turns green; existing review tests are updated to the new
  rule.
- Test: fake-CLI cases for red, fixed, transient error and repeated wake-ups.

**E. Observed stages.**
- Done when: an observed stage behaves exactly as section 6 and runs on change events,
  the producer's created, re-requested and completed events and a schedule; the newest result
  is chosen by creation; the GitHub renderer rejects a producer that is not a numeric App id
  and rejects GitHub Actions (App id 15368).
- Test: a vector per row of the section 6 table plus a wrong-producer case and a GitHub Actions
  producer case; a queued re-run after `PASS` turns the signal to `RUNNING` when it is created;
  governance interop.

**F. Gate check.**
- Done when: the governance workflow blocks on every non-`PASS` state of a blocking stage and
  ignores advisory stages, for managed and observed stages alike.
- Test: governance interop over the full state matrix.

**G. `standard` profile, `init`.**
- Done when: `standard` expands as in `02-canonical-stage-model.md`; `init` writes `profile: standard`, a `build:`
  block from the detected preset and a publisher block, and its output always passes `plan`; the
  repository-with-nothing-to-build recipe of section 2 passes `plan`.
- Test: end-to-end `init` then `plan` for three presets and for the recipe.

**H. Dogfood.**
- Done when: this repository's own build and tests run as Stagr stages; GitHub's own auto-merge,
  with the Stagr gate result as a required check, replaces this repository's hand-written
  auto-merge workflow (#265, section 7), in its own security-reviewed change; the old `Validate`
  workflow is then removed.
- Test: on a throwaway branch a deliberately broken test turns `build` red and the gate
  refuses; the fix turns it green and the gate accepts.

## 12. Decisions

| # | Decision | Status |
|---|---|---|
| 1 | Managed stages get no secrets; secret-bearing checks are observed | Owner confirmed |
| 2 | Gate defaults to blocking for every kind | Owner confirmed |
| 3 | `build:` is the single home of the `build` commands; unit tests run inside `build` | Owner confirmed (#265, section 5) |
| 4 | Delivery: this document plus one issue per item S and A–H | Owner confirmed |
| 5 | Executor model instead of a provider on every stage | Owner confirmed (#265) |
| 6 | Newest attempt wins, achieved by non-overlapping runs (no leases or tokens) | Owner confirmed (#265); runs verified not to overlap (section 9, fact 1) |
| 7 | Dependents wait on any non-`PASS` upstream | Owner confirmed (#265) |
| 8 | Security waits for review; reviews wait for `build` | Owner confirmed (#265) |
| 9 | Advisory exists only for `commands` and `observed` stages | Owner confirmed (#265) |
| 10 | A timeout is told from a cancel by the work job's run time, with the known limit of section 8, capability 4 | Owner confirmed (#265) |
| 11 | An observed stage takes the newest result, chosen by creation | Owner confirmed (#265) |
| 12 | An observed stage counts only a result the tool posts on the change; a tool that never posts one is not supported | Owner confirmed (#265) |
| 13 | The platform's own CI identity (GitHub Actions) is not an observed producer; that CI is a `commands` stage | Owner confirmed (#265) |

## 13. Not in scope

Deploy and release stages; toolchain and version provisioning; service containers; monorepo path
selection; detecting a test run that executed zero tests (that is the test tool's exit code);
post-merge builds on the default branch; support for platforms other than GitHub.
