# 04 — Execution and Security

A build or test stage runs **code from a pull request**. That is the most dangerous thing a CI
system does. This document says where that code may run, what it may touch, and how Stagr can
still trust the result. The rules here are neutral; the platform mapping is in 05.

## Two planes

```
 EXECUTION PLANE (untrusted)                 PUBLICATION PLANE (trusted)
 ---------------------------                 ---------------------------
 Runs the pull-request code.                 Never runs pull-request code.
 No Stagr credential.                        Holds the Stagr publisher credential.
 No secrets by default.                      Reads the platform's own outcome.
 Read-only repository access.                Writes the head-bound stage result.
 Its only output is an exit status.
```

A managed check stage renders **three units of work**, always in this order:

1. **Eligibility** (trusted, cheap). Decides whether this pull request may run this stage at all:
   trusted author, same repository (or allowed fork policy), pull request open and not a draft,
   head matches the event. Failing eligibility publishes nothing and starts nothing.
2. **Execute** (untrusted). Checks out the exact head commit, runs the configured commands,
   ends with an exit status. Nothing else leaves this unit.
3. **Publish** (trusted). Runs even if execute failed. Reads the platform's native outcome of
   *execute*, maps it (02), and publishes the head-bound stage result.

The same three units apply to every platform. How they are expressed (jobs, stages, pipelines)
is the renderer's business (05).

## Hard rules (each is a test)

| # | Rule |
|---|---|
| S1 | The execute unit never receives the publisher credential, and the publish unit never checks out or runs pull-request content. |
| S2 | The result is the **platform-attested outcome** of the execute unit. Not an artifact, log line, output variable, file, comment, or status that the executed code could have written. |
| S3 | The execute unit's repository token is read-only. It cannot create checks, statuses, comments, or contents. |
| S4 | The stage definition that runs comes from the **trusted base**, not from the pull request. A pull request cannot rewrite the commands that judge it. |
| S5 | Secrets are injected only into a managed stage that names them in `run.secrets`, and only when eligibility proves a trusted same-repository author. Never for forks. |
| S6 | Every managed stage has a timeout. There is no unlimited stage. |
| S7 | Commands and config values reach the shell as **data** (environment variable or file), never spliced into script text from event fields such as branch names or titles. |
| S8 | Anything Stagr renders that pulls third-party code (actions, images, plugins) is pinned by an immutable identifier. |
| S9 | The result names the head commit and is refused if the pull request head has moved (P6). |
| S10 | Untrusted code never shares a writable cache or workspace with a trusted job. |

## Threat table

| # | Threat | Control (rule) | Verified by |
|---|---|---|---|
| T1 | PR code steals the publisher credential or repository secrets | Credential only in the publish unit; execute has none (S1, S5) | Rendered-artifact test: no secret reference in execute; publish has no checkout |
| T2 | PR code forges a green result (writes a check, status, comment or artifact) | Read-only token (S3); result taken from platform-attested outcome (S2) | Test: execute permissions are read-only; publish never reads artifacts |
| T3 | PR rewrites the workflow or config so its own build passes trivially | Definition comes from the trusted base (S4); drift check in `stagr plan`/`doctor`; protected paths (below) | Test: PR-side edit of rendered file does not change what runs; drift is reported |
| T4 | Another actor creates a check with the same name as an observed stage | `observe.producer` mandatory; match on producer identity, not name; two producers is ambiguous and fails closed (02) | Vectors V-O3, V-O4 (07) |
| T5 | Old result replayed for a new commit | Head-bound results (S9, P6); a new push resets every stage | Vector V-H1 |
| T6 | `skipped`, `neutral`, `cancelled` accepted as a pass | Only `success` passes (02) | Vector V-N* (07) |
| T7 | Fork pull request gets secrets or runs privileged stages | `forkPolicy: DENY` by default; managed stages with secrets refuse forks (S5) | Existing fork tests extended to check stages |
| T8 | Poisoned dependency, cache or action in the rendered pipeline | Pinning (S8); no shared writable cache (S10); Stagr renders no cache keys | Test: every rendered `uses`/image is pinned; no cache step present |
| T9 | Secret values leaked through config, logs or errors | Names only in config; schema rejects invalid names; errors never echo secret-named fields (existing redaction) | Existing redaction tests + new `run.secrets` case |
| T10 | Config or event text injected into a shell command | Data-not-code delivery (S7); YAML is serialized by a library, not string-built | Test: hostile command/branch strings render as inert data |
| T11 | Runaway or abusive job burns runner time | Mandatory timeout (S6); trusted authors only; superseded runs cancelled | Test: timeout always present; concurrency group present |
| T12 | Persistent self-hosted runner carries state between jobs | Documented requirement: use ephemeral runners for execute units | Doc check (04 + 05 capability `ephemeral_runners`) |

## Definition integrity and protected paths

S4 stops a pull request from changing the commands that judge it *within the same run*. It cannot
stop a maintainer-approved pull request from changing the definition *for later runs*. Two
controls close that:

- **Drift check.** `stagr plan` and `stagr doctor` compare the rendered files with the
  repository. A definition that differs from what the config renders is reported.
- **Protected paths.** A pull request that changes the Stagr config or a rendered Stagr file
  (`.agentic/**` and the platform's rendered pipeline files) must not auto-merge; it needs a
  human decision. This uses the existing `human-merge` hard stop. (Decision D3 in 08: whether the
  toolkit applies the label automatically or only reports it. Recommendation: report it in
  `plan`/`doctor` first; automatic labelling is a follow-up.)

The commands *inside* the code under test (for example a script the build calls) are part of the
change being reviewed. Code review and security review cover them; Stagr does not pretend to.

## Secrets in check stages

- Default: **no secrets**. Build and unit test need none.
- A stage that needs one (for example an integration test against a database) lists the secret
  **name** in `run.secrets`. The renderer maps names to the platform's secret store. Values
  never appear in config, rendered files, logs or errors.
- A stage with secrets is *privileged*. It follows the existing privileged-workflow rules
  (doc 05): trusted author, same repository, definition from the trusted base.
- A privileged execute unit still must not run untrusted code with the publisher credential;
  S1 is unconditional.

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

- It does not sandbox the code under test; the platform's runner isolation does. Teams with
  stricter needs use ephemeral runners or `execution: observed` with their hardened CI.
- It does not detect a test suite that has been weakened inside the pull request. That is the job
  of code review, security review, and required-coverage tooling run as its own stage.
