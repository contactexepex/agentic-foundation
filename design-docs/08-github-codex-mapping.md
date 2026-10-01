# Stagr Neutral Core — GitHub Adapter and Codex Backend Mapping

**Status:** Target design. What is built today is in
[ARCHITECTURE.md, section 8](../docs/ARCHITECTURE.md#8-status--roadmap).

---

## Overview

This document holds everything GitHub-specific: how the GitHub adapter maps the neutral model,
how it supplies facts to the rules engine and carries out its effects, and how the Codex backend
fits. The last section describes this repository's own hand-written workflows, which are our
process and not a product feature.

The neutral documents (00–07, 09) name no platform; when they need a GitHub detail, they point
here. GitHub-specific parts of the check-stage design stay in `09-check-stages.md`, sections 8
and 9.

---

## Neutral-to-GitHub mapping

| Neutral concept | GitHub |
|---|---|
| Change (`02-canonical-stage-model.md`) | Pull request, the first change kind implemented |
| Revision | The pull request's head commit SHA, always the full 40 characters |
| `platform.scm`, `platform.ci` | `github` |
| `StageTrigger.CHANGE_OPENED` | `pull_request_target: [opened, reopened, ready_for_review]` |
| `StageTrigger.CHANGE_UPDATED` | `pull_request_target: [synchronize]` |
| `StageTrigger.MANUAL` | `workflow_dispatch` |
| `InvocationKind.COMMENT_COMMAND` | `gh pr comment <pr> --body-file <file>` with the trusted commenter token |
| `InvocationKind.CI_STEP` | A GitHub Action step. Not rendered: V-S08 rejects it |
| `InvocationKind.RUN_COMMANDS` | The untrusted work job of the stage workflow (`09-check-stages.md`, section 8) |
| `InvocationKind.READ_RESULT` | A job that reads Check Runs (`09-check-stages.md`, section 8, capability 9) |
| `EvidenceKind.REVIEW_RESULT` | Codex bot comment containing `codex-pull-request-review-summary` and its review table |
| `EvidenceKind.COMMENT_MATCH` | A pull request (issue) comment evaluated against the backend-defined selector |
| `EvidenceKind.CHECK_RESULT` | A Check Run on the head commit, matched by name and `.app.id` |
| `EvidenceKind.WORKFLOW_RESULT` | `needs.<work job>.result` |
| Result carrier of a `StageResultSignal` | Check Run `stagr/stage/<stageId>` written by the Stagr GitHub App, with the signal as JSON in `output.summary` |
| Result carrier of a `RouteClassification` | Check Run `stagr/route-classification` written by the Stagr GitHub App |
| Gate result | The check of the governance workflow's job, required by branch protection |
| Publisher identity | The Stagr GitHub App (`platform.publisher.app_id`) |
| `producedBy` / `createdBy` identity | A GitHub login. A login ending in `[bot]` matches only a Bot actor, never a person with a similar name |
| `AuthorRole` | `author_association`: `OWNER`, `MEMBER`, `COLLABORATOR`, `CONTRIBUTOR` |
| Same-repository rule | `head.repo.full_name == GITHUB_REPOSITORY` |
| Review discussions (`DiscussionPolicy`) | Unresolved review threads on the pull request |
| Secret reference | `${{ secrets.<NAME> }}` |
| Engine file | `.github/stagr/engine.py`, run by every generated workflow with `python3` |

---

## The rules engine on GitHub: facts in, effects out

Every generated workflow runs the one engine file (`06-runtime-boundary.md`, "The engine file").
The runtime source is no longer pasted into each workflow.

- **Facts** come from the event payload and the GitHub API (`gh`): the pull request (state,
  draft, `author_association`, head repository, base branch, mergeability), its head SHA, the event
  name, the Check Runs on the head, comments, review threads, and `needs.<work job>.result`.
- **Effects** are carried out by the workflow step that ran the engine: posting the invocation
  comment, and creating or updating a Check Run (a stage result or the gate result).

---

## Trust on GitHub

### Privileged contexts and tokens

The privileged CI context is `pull_request_target`. A write-capable platform token is
`GITHUB_TOKEN` with write scopes, or the `id-token: write` permission that requests an OIDC token.

### `pull_request_target` safety

GitHub's `pull_request_target` event gives a workflow access to repository secrets and
write-capable tokens, even when triggered by a fork pull request. This is a known
repository-compromise vector. The PlatformRenderer **must** enforce the following when
generating workflows that use `pull_request_target` with secrets:

- The workflow must verify `author_association` is in `trustedRoles` before using any
  secret.
- The workflow must verify the pull request head is from the same repository
  (`head.repo.full_name == GITHUB_REPOSITORY`) before proceeding.
- The workflow must never check out, execute, or evaluate pull request head content inside a job
  that holds secrets.
- All of the above checks must be enforced in-script (a `pull_request_target` job-level
  `if:` cannot safely guard these conditions because the pull request fields are not available
  for all trigger events).

### Result carriers

A Check Run is associated with the GitHub App that creates it, so its publisher's App id is
verifiable. Commit statuses carry no App identity and are forgeable by any token with
`statuses: write`, so they are **never** used for a `StageResultSignal` or a
`RouteClassification`. The governance workflow verifies that each Check Run it reads was written
by the Stagr App (`StageResultSpec.provenance.publisherIdentity`) and rejects any other.

Writing Check Runs needs the `checks: write` permission in the stage and routing workflows, and
the Stagr App needs the Checks read and write permission. These are PlatformRenderer
responsibilities, not `ExecutionPlan` fields. `stagr doctor` V-E03 checks the repository's
workflow permissions and V-E02 checks that the App is installed with these capabilities
(`07-validation.md`).

---

## Reconciliation events on GitHub

| Neutral event (`06-runtime-boundary.md`) | GitHub event |
|---|---|
| A comment is created or edited on the change | `issue_comment: [created, edited]` |
| A result on the revision completes | `check_run: [completed]`, `check_suite: [completed]` |
| Scheduled sweep | `schedule` (every 5 minutes) |

These events never map to a `StageTrigger` and never post a new invocation on their own. How the
generated workflow uses them is in "Reconciliation and result signaling" below.

---

## Codex backend

- **Evidence.** The `review` stage uses `REVIEW_RESULT`: the Code Review row of the Codex
  summary comment, with `COMPLETED`. The `security` stage uses `COMMENT_MATCH` on the marker Codex
  embeds in the same summary comment, `<!-- codex-security-review:v1 {..."status":"completed"} -->`,
  matched with the compound selector `codex-security-review:v1 status=completed`
  (`06-runtime-boundary.md`).
- **Spike A (invocation independence).** `@codex review` and `@codex security review` are
  independently triggerable comments. The order of the two reviews is a default of the `standard`
  profile (`09-check-stages.md`, section 10), not a backend requirement.
- **Spike B (finding correlation).** The GitHub API exposes no field that reliably ties a review
  thread to the stage invocation that produced it when both reviews run under the same Codex bot
  identity on the same head commit. The Codex backend therefore uses the shared-scope mode of
  `06-runtime-boundary.md` (`invocationCorrelation = null`): every unresolved Codex-bot thread on
  the head blocks both stages.
- **Candidate bindings for `invocationCorrelation`**, should a backend need one. The binding must
  use a field the GitHub review-thread API actually exposes; a back-reference to the triggering
  issue comment is not available.
  - A `pull_request_review_id`, if the backend creates one formal pull request review per stage
    invocation.
  - A backend-emitted correlation marker in every finding comment body.
  - A backend-specific task or invocation id exposed in the backend's completion artifact and
    echoed into each finding.

---

## Reconciliation and result signaling (GitHub renderer)

This is how the generated `stage-<id>.yml` implements the reconciliation model in
`06-runtime-boundary.md`.

- **Jobs.** One file per stage. `execute` runs on the stage's declared triggers and, only for a
  stage that declares dependencies, on the `check_run` / `check_suite` wake-ups described under
  "Dependency wake-ups" below. `reconcile` runs on `issue_comment` events for a pull request, and
  only when the comment author is a declared evidence producer. `sweep` runs on a schedule (every 5
  minutes) and runs the same routine for every open pull request. Every stage has `reconcile`
  and `sweep`, because every plan must declare evidence (see below). Each job has an explicit
  `github.event_name` condition, so a wakeup never re-runs the backend, and `synchronize` is never
  a wakeup. `check_suite` is not used to observe evidence in V1: that serves check-based evidence,
  which V1 rejects (see below).
- **State is observed, not remembered.** Every run re-reads the pull request, its comments, its
  review threads and the stage's Check Run for the current head. Missed, repeated or reordered
  events therefore cannot produce a wrong signal; the sweep is only a backstop.
- **One Check Run per stage and head.** Only the `execute` job creates it. `reconcile` and
  `sweep` update it in place. Governance rejects duplicates and cannot repair them, so creation
  has a single owner that is already serialized by the stage's concurrency group.
- **Terminal states.** The reconciliation termination rule is in `06-runtime-boundary.md`. On
  GitHub, a `failed` signal is retried only by re-running the stage's `execute` job, and a write
  happens only when the signal changed.
- **Evidence is authenticated.** Only comments written by `EvidenceSpec.produced_by` count, and
  evidence must be bound to the current head commit.
- **Findings.** For `NO_OPEN_THREADS`, an unresolved thread counts when its first comment is by
  `FindingScopeSpec.created_by` and, if the scope is head-bound, when its review commit is the
  current head. A thread whose review commit is unknown counts as open (fail closed).
- **Rejected at render time** (`stagr apply` fails; nothing weaker is generated): evidence kinds
  other than `REVIEW_RESULT` and `COMMENT_MATCH`; evidence that is not head-bound or has no
  `produced_by`; `invocation_correlation`; any invocation kind other than `COMMENT_COMMAND`; and
  plans with no evidence, because a `COMMENT_COMMAND` invocation finishes asynchronously and
  nothing else could prove it finished.
- **Events without a pull request** (`workflow_dispatch`) publish no signal.
- **Invocation and idempotency (`COMMENT_COMMAND` backends).** The `execute` job has one step,
  "Invoke backend (idempotent)", that runs the engine in `invoke` mode. In this order it
  (1) skips if the pull request is not eligible or the event's head is stale; (2) skips if the
  `EvidenceSpec` already holds for the current head (completion guard); (3) skips if a still-valid
  in-flight marker exists for this stage and this exact head; (4) otherwise posts the backend
  comment (`Invocation.params["body"]`) with the in-flight marker of `06-runtime-boundary.md`
  appended, its expiry in UTC. A skipped step exits successfully, so the "Publish result signal"
  step still runs and reports `running` or the completed result. This step runs inside the
  stage's concurrency group.
- **The in-flight marker is authenticated.** Comments on a public repository are written by
  anyone, so a forged far-future marker could otherwise stop an invocation for ever. A marker
  counts only if the comment's author is the account that owns the invoke token (its id, login
  and type come from `GET /user` at run time and must all match, so a look-alike name or a Bot
  twin never matches) and the comment's `author_association` is one of the `TrustPolicy` roles.
  The marker must also name this exact stage id and the full 40-character head SHA. Markers
  without an expiry, with an unparseable expiry, or for another stage or head are ignored, and an
  expiry that is not in the future counts as expired. Consequently the account behind
  `TRUSTED_COMMENTER_TOKEN` must have a role listed in `TrustPolicy.trusted_roles`; otherwise its
  markers are never believed and each run posts again.
- **Lease length** is `Invocation.params["lease_minutes"]` (backend-defined; 30 when absent),
  checked at render time: an integer from 1 to 1440, anything else fails `stagr apply`. `body`
  must be non-empty text and the plan must declare a resolved `TRUSTED_COMMENTER_TOKEN` secret.
- **Credentials.** Only the invoke step holds the backend secret. It reaches the engine as
  `TRUSTED_COMMENTER_TOKEN`, and the engine hands it to `gh` as `GH_TOKEN` for that step only.
  The App installation token is never present in the invoke step; the eligibility step,
  `reconcile` and `sweep` hold only the App token (`reconcile` and `sweep` with
  `permissions: {}`).
- **Eligibility.** The first step after the token is "Check eligibility". It runs the engine's
  eligibility checks (`06-runtime-boundary.md`, "Eligibility") and writes `proceed=true` or
  `proceed=false` to the step output; the invoke step runs only when it is `true`, and a failed
  eligibility step also stops it. The same eligibility code runs in `publish`, `reconcile` and
  `sweep`, so no mode can act on a pull request another mode refused. An ineligible run invokes
  nothing and writes no signal; the "Publish result signal" step still runs and repeats the same
  checks, so it publishes nothing either. The invoke step keeps its own pull-request checks (it
  has no App token, so it cannot read Check Runs); route and dependencies are decided once by the
  eligibility step just before it.
- **Route applicability.** When `RoutingPolicy.fast_path` is configured, the rendered
  configuration carries the stage ids of the FAST and NORMAL routes, and the engine reads the
  `stagr/route-classification` Check Run for the current head. It is trusted only if the Stagr
  App wrote it, it is bound to the head, it is completed, and its title is exactly
  `RouteClassification=FAST` or `RouteClassification=NORMAL`; two Stagr runs are an error, and
  a run from another app is ignored. A stage that is not listed for the route does not run. The
  routing workflow starts at the same moment as the stage workflow, so a classification that is
  still missing is waited for (up to 3 minutes, only in the eligibility step); after that the stage
  fails closed and starts on its next execute run.
- **Dependencies.** For each stage in `NormalizedStage.dependencies` the engine reads that
  stage's Check Run (`stagr/stage/<id>`) for the current head. It counts only if it is the single
  Check Run of that name written by the Stagr App, and the JSON in `output.summary` has
  `schemaVersion` 1 and states the same stage id and head SHA. `state` and `conclusion` come from
  that payload, never from the native Check Run fields. The dependency rule
  (`06-runtime-boundary.md`) then decides; while it says "wait", nothing is invoked and nothing is
  written. Two Stagr runs for one dependency are an error and nothing is written.
- **Dependency wake-ups.** A stage with dependencies also subscribes to `check_run: completed`
  and `check_suite: completed`, so it starts when the upstream signal first passes, without a new
  push. These events fire for every check in the repository, so the `execute` job's `if:` lets
  through only a `check_run` written by the Stagr App for one of the upstream stage Check Runs,
  or a `check_suite` written by the Stagr App, and only when the payload names a pull request of
  this repository. The stage's own Check Run (`stagr/stage/<its id>`) is not upstream, so writing
  its own signal cannot wake it through `check_run`. A Stagr `check_suite` does follow every Stagr
  write, but a wake-up that changes nothing writes nothing, so it ends there. A wake-up run
  differs from a pull request run in one way: a stage whose own signal is already `pass` or
  `failed` is left alone. `failed` is terminal for wake-ups and the sweep; only a re-run of the
  execute job (a `pull_request_target` event or a manual re-run) retries, otherwise unrelated
  Check Run events could re-run a failed paid backend in a loop. The pull request number and head
  come from the event payload (`pull_requests[0]`, `head_sha`) and are checked against the API
  like any other event, so a wake-up about a superseded head does nothing.
- **Concurrency of wake-ups.** A relevant wake-up uses the same concurrency group as the pull
  request's other events (`stagr-<id>-<pull request number>`), so the execute job stays the only,
  serialized creator of the Check Run. An irrelevant `check_run` / `check_suite` event gets a group
  of its own (the run id): with `cancel-in-progress: false` GitHub keeps one pending run per group
  and replaces it with the next one, so an unrelated event in the shared group could push out a
  real wake-up. Two relevant events can still replace one another; that is harmless because every
  run reads the current state instead of trusting its event. Every check in the repository still
  starts a run of each dependent stage's workflow, which is skipped by the `if:` conditions.
- **Known limitation: the sweep cannot start a dependent stage.** The sweep re-reads the upstream
  signals of every open pull request, so it sees an upstream `blocked` -> `pass` flip (which may
  raise no `check_run` event). It uses them to complete an existing signal and to leave it alone
  while an upstream has not passed. It cannot start a stage
  that has not started, because starting needs the backend secret and creating the Check Run,
  and the sweep holds neither. Such a stage starts the next time its execute job runs: a wake-up
  event of an upstream signal, a reopen, `ready_for_review`, or a manual re-run of the workflow. The
  sweep logs "dependencies have passed but the stage has not started" for it.
- **Known limitation: fork pull requests and wake-ups.** The Check Run payload names no pull
  request for a fork, so a fork pull request (allowed only for a non-privileged stage under
  `ForkPolicy.ALLOW_UNPRIVILEGED`) is not woken by upstream signals. Its dependent stage starts
  only if the upstream had already passed when a pull request event or a manual re-run arrived.
- **Known limitation: the sweep cannot re-invoke.** The sweep job must not hold the backend
  secret, so it never posts an invocation. If a backend drops an invocation and the lease expires,
  the pull request stays `running` until the `execute` job next runs for that same head (a
  reopen, `ready_for_review`, or a manual re-run of the workflow). A new push starts a new head
  and is invoked normally. This narrows the recovery rule in `06-runtime-boundary.md`, which
  allows the sweep to re-post.
- **Other invocation kinds.** The GitHub renderer renders only `COMMENT_COMMAND`. A backend whose
  plan needs another kind (`CI_STEP`) is rejected by V-S08 (`07-validation.md`), and the renderer
  itself refuses it.
- **Stagr App permissions** used at run time: Checks (write), Pull requests (read) and Issues
  (read).

---

## This repository's hand-written workflows (our process, not the product)

This repository still runs hand-written workflows. They stay until dogfooding (#257) replaces
each one with generated workflows (#265, section 6, item B6):

| Workflow | What it does | Replaced by |
|---|---|---|
| none: the Codex App reviews every new commit by itself | Code review | The generated `review` stage |
| `request-final-security-review.yml` | Requests the security review once the code review has converged | The generated `security` stage |
| `fast-ai-code-review.yml` | Classifies the route | The generated routing workflow |
| `auto-merge-foundation-prs.yml` | Merges a ready pull request | GitHub's own auto-merge, with the Stagr gate result as a required check (#265, section 7) |

The **`human-merge` label** and the two merge lanes belong to this repository's process only
(`AGENTS.md`, "Merge lanes"); the product has neither (#265, addendum, decision 23).

`request-final-security-review.yml` orders the two reviews with its own wait on the Codex summary
rows. A generated `security` stage orders them through its declared `depends_on: [review]` and
the dependency rule instead (Renderer Invariant R1, `04-render-time-architecture.md`).
