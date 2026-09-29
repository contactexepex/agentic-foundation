# 04 — Execution and Security

A build or test stage runs **code from a pull request**. That is the most dangerous thing a CI
system does. This document says where that code may run, what it may touch, and how Stagr can
still trust the result. The rules here are neutral; the platform mapping is in 05.

## Two planes

```
 EXECUTION PLANE (untrusted)                 PUBLICATION PLANE (trusted)
 ---------------------------                 ---------------------------
 Runs the pull-request code.                 Never runs pull-request code.
 No Stagr credential.                        Its units (eligibility, publish) hold the
 No secrets by default.                      Stagr publisher credential.
 Read-only repository access.                Reads the platform's own outcome.
 Its only output is an exit status.           Writes the head-bound stage result.
```

A managed check stage renders **three units of work**, in this order:

1. **Eligibility** (trusted, cheap; holds the publisher credential and, like publish, never checks
   out or runs pull-request content). Decides whether this pull request may run this stage at all:
   trusted author, same repository, pull request open and not a draft, head matches the event,
   route applies, and every dependency has passed. Failing any check publishes nothing and starts
   nothing. Only after **all** of them pass does it write the stage's `RUNNING` result for the head
   (the lease, rules in 06), then start the work. It is the **only** unit that creates the stage's
   result (the Check Run on GitHub); every other trusted writer only updates it.
2. **Work** (untrusted). Checks out the exact head commit, runs the configured commands, ends with
   an exit status. Nothing else leaves this unit.
3. **Publish** (trusted). Runs even if the work failed or was cancelled. Reads the platform's
   native outcome of *work*, maps it (02), and publishes the head-bound stage result. It is the
   **only** writer of the stage's final result, and it only *updates* the result that eligibility
   created. The `RUNNING` result is written only by the eligibility unit, never by the work unit.
   Eligibility and publish never share a concurrency group, so a later job can never evict a
   queued publisher (06, "The lease").

Note the naming: today's generated GitHub workflow has one job called `execute` that holds
eligibility, invocation and publish steps together. Splitting it into three separate jobs is a
restructuring of that workflow, not a reuse (delivery I5). To avoid confusion this plan calls the
untrusted unit the **work unit**.

The same three units apply to every platform. How they are expressed (jobs, stages, pipelines)
is the renderer's business (05).

## Hard rules (each is a test)

| # | Rule |
|---|---|
| S1 | The work unit never receives the publisher credential. The eligibility and publish units, which hold it, never check out or run pull-request content. |
| S2 | The result is the **platform-attested outcome** of the work unit. Not an artifact, log line, output variable, file, comment, or status that the executed code could have written. |
| S3 | The work unit's repository token is read-only and is **not persisted** into the checked-out repository (no stored credentials in the workspace). It cannot create checks, statuses, comments, or contents. |
| S4 | The stage definition that runs comes from the **trusted base**, not from the pull request, wherever the platform can do so (05, `definition_source`). Where it cannot, protected paths are mandatory (below). |
| S5 | Secrets are injected only into a managed stage that names them in `run.secrets`, and only when eligibility proves a trusted same-repository author. Never for forks. |
| S6 | Every managed stage has a timeout. There is no unlimited stage. |
| S7 | Commands and config values reach the shell as **data** (environment variable or file), never spliced into script text from event fields such as branch names or titles. |
| S8 | Anything Stagr renders that pulls third-party code (actions, images, plugins) is pinned by an immutable identifier. |
| S9 | The result names the head commit and is refused if the pull request head has moved (P6). |
| S10 | The work unit renders no cache restore or save, and never shares a writable workspace with a trusted job. |
| S11 | The publisher credential is scoped so that only the trusted default-branch definition can read it (an environment or protected-variable restriction), not every branch workflow. |
| S12 | `run.secrets` can never name a credential Stagr itself uses (03, rule 4). |
| S13 | **Managed stages never run fork code.** Fork policy `ALLOW_UNPRIVILEGED` (design doc 05) does not extend to managed check stages; a fork pull request only gets the review stages' existing behavior. |
| S14 | Blocking managed stages run on ephemeral runners. A platform without them cannot host a blocking managed stage (05). |

## Threat table

| # | Threat | Control (rule) | Verified by |
|---|---|---|---|
| T1 | PR code steals the publisher credential or repository secrets | Credential only in the trusted eligibility and publish units, which never check out or run pull-request content (S1, S5); credential restricted to the default branch (S11) | Rendered-artifact test: no secret or credential reference in the work unit; eligibility and publish have no checkout |
| T2 | PR code forges a green result (writes a check, status, comment or artifact) | Read-only, non-persisted token (S3); result taken from platform-attested outcome (S2). Note that on GitHub the built-in workflow token can itself create check runs when granted `checks: write`; the work unit is never granted it | Test: work permissions are read-only; publish never reads artifacts |
| T3 | PR rewrites the workflow or config so its own build passes trivially | Definition from the trusted base where possible (S4); drift check; protected paths (below) | Test: PR-side edit of rendered file does not change what runs; drift is reported |
| T4 | Another actor creates a result with the same name as an observed stage | `observe.producer` mandatory; match on producer identity, never name; a shared CI identity is not enough on its own (05, provenance); ambiguous results fail closed (02) | Vectors V-O* (07) |
| T5 | Old result replayed for a new commit | Head-bound results (S9, P6); a new push resets every stage | Vector V-H1 |
| T6 | `skipped`, `neutral`, `cancelled` accepted as a pass | Only `success` passes (02) | Vectors V-N* (07) |
| T7 | Fork pull request gets secrets or runs code | Managed stages refuse forks (S13) | Test: fork event produces no work unit |
| T8 | Poisoned dependency, cache or action in the rendered pipeline | Pinning (S8); no cache steps (S10); residual risk R1 below | Test: every rendered `uses`/image is pinned; no cache step present |
| T9 | Secret values leaked through config, Stagr output or errors | Names only in config; schema rejects invalid names; errors never echo secret-named fields. Leak by the code under test itself: R4 | Redaction tests + `run.secrets` case |
| T10 | Config or event text injected into a shell command | Data-not-code delivery (S7); YAML serialized by a library, not string-built | Test: hostile command/branch strings render as inert data |
| T11 | Runaway or repeated jobs burn runner time | Mandatory timeout (S6); a wake-up never re-runs work that already has a result for the head (06); the work unit has its own cancel-superseded concurrency group; eligibility has its own non-cancelling group per stage and pull request; publish has a group per workflow run (06) | Tests: timeout present; wake-up chatter starts no second run; a later wake-up does not evict a queued publisher; group keys |
| T12 | Persistent self-hosted runner carries state between jobs | Blocking managed stages require ephemeral runners (S14) | Capability refusal test (05) |
| T13 | A same-repository branch workflow reads repository secrets, including the publisher key | Credential scoped to the trusted default-branch definition (S11); `doctor` checks the scope when the platform exposes it | `doctor` test with a fake platform |
| T14 | Dependency-update bots or other non-trusted authors deadlock the gate | Not solved by loosening trust. Decision D10: bot pull requests get no managed stages and need a human to re-author or a documented allowlist | See 08 |
| T15 | A trusted actor repeatedly re-runs or pushes to replace a `RUNNING` or `FAILED` result (churn, runner cost) | Replacing a result needs write access (explicit re-run) or trusted-pull-request authorship (pull request event), both checked by eligibility (S1); it cannot change the head (S9); it is no larger a denial-of-service surface than those actors already have by pushing or re-running; attempt tokens (06) stop an older attempt from overwriting a newer result | Tests: an untrusted trigger replaces nothing; an older attempt publishes late and is a no-op |

## Definition integrity and protected paths

S4 stops a pull request from changing the commands that judge it *within the same run*, on
platforms that can take the definition from the trusted base. On platforms that cannot, and for any
platform against a maintainer-approved pull request that changes the definition for *later* runs,
two controls apply:

- **Drift check.** `stagr plan` and `stagr doctor` compare the rendered files with the
  repository. A definition that differs from what the config renders is reported.
- **Protected paths.** A pull request that changes the Stagr config or a rendered Stagr file
  (`.agentic/**` and the platform's rendered pipeline files) must not auto-merge; it needs a
  human decision. This is the existing `merge.protected_paths` mechanism (default
  `.github/workflows/**` and `.agentic/**`) plus the `human-merge` hard stop. (Decision D3 in 08:
  whether the toolkit also labels automatically. Recommendation: report it in `plan`/`doctor`
  first.) When `definition_source` is `pr_branch`, empty `protected_paths` is a `doctor` error.

The commands *inside* the code under test (for example a script the build calls) are part of the
change being reviewed. Code review and security review cover them; Stagr does not pretend to.

## Residual risks stated openly

| # | Risk | Why it remains | Position |
|---|---|---|---|
| R1 | Cache poisoning through the CI platform's cache service | On GitHub, a job running on `pull_request_target` uses the base branch's cache scope, and the job's runtime cache token is reachable from any command it runs. Rendering no cache steps (S10) does not remove that token | Accepted for trusted same-repository authors (the threat model already excludes others); revisit when a platform offers a per-job cache-off switch or a required-workflow mechanism. Decision D13 |
| R2 | A malicious change inside the code under test | Stagr runs what the repository says | Covered by code and security review, not by Stagr |
| R3 | Platform runner isolation flaws | Outside Stagr | The platform's responsibility; teams with stricter needs use `execution: observed` with hardened CI |
| R4 | Code in a stage with `run.secrets` can leak that secret (encode, send, print) | Stagr must run the pull-request code with the secret to do the job; masking is exact-match only | Accepted for trusted same-repository authors. Use disposable, least-privilege credentials; anything that needs stronger isolation uses `execution: observed` with hardened CI |

## Secrets in check stages

- Default: **no secrets**. Build and unit test need none.
- A stage that needs one (for example an integration test against a database) lists the secret
  **name** in `run.secrets`. The renderer maps names to the platform's secret store. Stagr never
  writes values into config, rendered files, its own output or errors.
- The work unit still runs pull-request code, so that code can read the value. Platform log
  masking only matches the exact text and does not stop code from encoding or sending it
  elsewhere (R4). Give such a stage a disposable, least-privilege test credential, never a
  production one.
- A stage with secrets is *privileged*. It follows the existing privileged-workflow rules
  (design doc 05): trusted author, same repository, definition from the trusted base.
- S1 is unconditional: a privileged work unit still never receives the publisher credential.

## Observed stages

An observed stage runs no code through Stagr, so the execution plane does not exist. The
publication plane still applies: a trusted unit reads exactly one named result, checks that its
producer matches `observe.producer`, that it is bound to the current head, and maps its native
outcome (02). If the result is absent, ambiguous, stale or from another producer, the stage is not
passed.

## Logging and evidence

- Stagr publishes only the small stage result plus a link to the platform's own run page. It does
  not copy logs, test reports or artifacts (Charter section 5).
- Commands and their output stay in the platform, under the platform's own retention and masking.

## What this design does not claim

- It does not sandbox the code under test; the platform's runner isolation does.
- It does not detect a test suite that has been weakened inside the pull request. That is the job
  of code review, security review, and required-coverage tooling run as its own stage.
