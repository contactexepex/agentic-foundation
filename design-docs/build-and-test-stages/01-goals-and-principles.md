# 01 — Goals and Principles

## Goals

1. **The baseline works out of the box.** A new repository gets four blocking stages: *build*
   (compiles), *unit tests*, *code review*, *security review*. A pull request merges only when
   all four are complete and green and every review comment is resolved.
2. **Teams can extend it.** Integration tests, performance tests, SQL validation, SAST, DAST,
   dependency and license scans are added as more stages. Each is `blocking` or `advisory`.
3. **Platform-neutral.** The contract, the config and the result model contain no GitHub-only
   (or GitLab-only, ...) concepts. Each platform is one renderer plus a declared capability set.
4. **Integrates with existing CI.** A team that already has Jenkins, GitLab CI, Azure Pipelines,
   CircleCI, SonarCloud, etc. can plug that in as-is, without rewriting it.
5. **Safe by construction.** Untrusted pull-request code never runs next to trusted credentials,
   and a result can never be forged, replayed, or borrowed from another commit.
6. **Small to configure.** The common repository needs about ten lines (Charter section 6).

## What "blocking" and "advisory" mean

- **Blocking:** the stage must finish, must be green, and all of its review comments must be
  resolved, before the pull request can merge.
- **Advisory:** the stage reports (a check result and/or comments) but never blocks the merge.

## The baseline every pull request must meet

| Stage | Meaning | Required |
|---|---|---|
| Build | The code compiles / packages | Always for code repositories |
| Unit tests | All unit tests pass | Always for code repositories |
| Code review | Review agent finished, all comments resolved | Always |
| Security review | Security agent finished (OWASP, CVE, pen-tester view), all comments resolved | Always |
| Integration / performance / SQL / SAST / DAST / scans | Team-defined | Optional per team |

`stagr init` always generates the four baseline stages. A repository with nothing to build (for
example documentation only) turns `build` and `unit-test` off explicitly with `enabled: false`;
the schema keeps `build:` optional.

## Non-goals

- Stagr does **not** run builds or tests itself, host runners, store artifacts or logs, or show
  dashboards (Charter section 5). The platform runs the work.
- No general workflow language: no matrices, services, caches, containers, conditional steps or
  artifact publishing in Stagr config. Those belong to the CI system; teams use *observed* mode
  for anything richer.
- No deployment or release stages in this plan (`deploy` is a separate, later design).
- No new merge rules beyond "all blocking stages green and all comments resolved".
- Not solved here, and documented as limits: toolchain and version provisioning (the platform
  runner image and the team's own commands do that), service containers, monorepo path
  selection, and detecting a test run that executed zero tests (that is the test tool's exit
  code semantics).

## Principles (each one is testable)

| # | Principle | What it means in practice |
|---|---|---|
| P1 | **Neutral core, adapters at the edge** | Only a platform renderer knows platform names, events, APIs. The core model never does. |
| P2 | **Wiring, not work** | Stagr declares and renders; the platform executes. A managed stage is a thin adapter step on the user's runner (Charter section 2). |
| P3 | **Untrusted code never meets trusted credentials** | The job that runs pull-request code has no Stagr credential and no secrets by default; the units that hold the credential never run pull-request code. |
| P4 | **Evidence is observed, never self-reported** | A result counts only if a trusted party read it from the platform. The code under test cannot mark itself green. |
| P5 | **Fail closed** | Missing, unknown, skipped, cancelled, stale or ambiguous means *not passed*. Only an explicit success passes. |
| P6 | **Head-bound** | Every result names the exact commit. A result for an older commit never satisfies a newer one. |
| P7 | **Reference, do not re-declare** | If the platform or CI already owns a fact (a check name, a runner, a trigger), reference it by name. |
| P8 | **One contract, proven by shared test vectors** | Every platform implementation is tested against the same input/output vectors (see 07). |
| P9 | **Additive and versioned** | New capability arrives as optional fields and new versions. Existing configs keep working. |

## Constraints inherited from existing documents

- Charter sections 2, 4, 5, 6: control plane, litmus test, non-goals, configuration budget.
- Design doc 04, invariants R1 to R4: no invented dependencies; evidence does not gate
  invocation; merge policy is read-only at run time; signals are emitted, never assumed.
- Design doc 05: trust policy, fork policy, human-merge hard stop.
- Design doc 06: head-bound evidence, authenticated signals, reconciliation, idempotency.
- `AGENTS.md` threat model: automation is driven only by trusted authors on same-repository
  branches; PR content is untrusted data; the untrusted implementer must never reach the
  trusted publisher.
