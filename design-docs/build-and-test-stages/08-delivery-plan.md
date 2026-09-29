# 08 — Delivery Plan

This document turns the design into work items. Every item has **acceptance criteria** and a
**test item**, as `AGENTS.md` requires before a story can start. Issues are created from this
document only **after** this plan is merged.

## Decisions to confirm (with recommendations)

Reviewers: please confirm or change each one (D1 to D13). Nothing below is built until they are settled.

| # | Decision | Recommendation | Alternative and why not |
|---|---|---|---|
| D1 | Stage kinds for optional checks | Reuse `build` and `test`; everything else is `custom`, named with `name:` | A growing enum (`integration`, `perf`, `sast`, ...): forces a core change per tool |
| D2 | How to express who runs the work | One key, `execution: managed \| observed` | Separate stage types: doubles every rule and every test |
| D3 | Changes to Stagr config or rendered files | `plan`/`doctor` **report** that human review is needed; automatic labelling later | Auto-apply `human-merge` now: a new mutating behaviour that needs its own security review |
| D4 | Where `build` sits | `build` first; `unit-test` and both reviews depend on it and not on each other's outcome (except as D11 decides for the two reviews) | Reviews after unit tests: slower, no added safety. Everything parallel: pays for reviews of code that does not compile |
| D5 | `modules.sonar` | Keep as a deprecated alias for one release, warn, then remove | Remove now: breaking. Keep forever: two fail-open/fail-closed behaviours |
| D6 | Advisory stage that fails | Stagr's published result shows an informational (non-failing) value; the signal payload still says `FAILED`; the work unit's own check keeps its real outcome | Show red: trips "all checks must pass" rules by accident. `continue-on-error`: destroys the attested outcome |
| D7 | Granularity of `build` | One `build` stage runs install, lint, typecheck; `unit-test` separate; extra stages are config | One stage per command: many signals, slower, more noise |
| D8 | Upstream not green | Dependents **wait** on every non-`PASS` upstream, including state `FAILED`, instead of failing terminally (06) | Keep propagation: paid review stages stuck after a fixed test or a transient `build` error |
| D9 | Re-run after a published `PASS` | `PASS` is final for a head (matches today's runtime); a new push resets | Latest attempt always wins: flip-flopping results and a rewrite of the reconcile rule |
| D10 | Dependency-update bots and other non-trusted authors | No managed stages for them and no loosening of trust; the team either re-authors the change or adds an explicit, reviewed allowlist in a later design | Trust bots by default: widens the attack surface the threat model closes |
| D11 | Order of code review and security review | Owners decide. This repository's contract says in sequence; design doc 08 plans independent stages. This plan works with either | Choosing silently in this plan: would contradict one of the two documents |
| D12 | Compile step in `build:` | Add optional `build.commands.build` with a default per preset | Leave as is: "compiles" is not guaranteed by `install`/`test` for every preset |
| D13 | Cache poisoning residual risk on GitHub (04, R1) | Accept and document for trusted same-repository authors | Run PR code on `pull_request`: gives up base-branch workflow definition (S4) |

## Phases

Dependencies: P1 first; P2, P3 and P5 can then run in parallel; P4 needs P3; P6 needs P1 and P3;
P7 needs P3 and P4.

### P1 Foundation (config and neutral core)

**I1. Schema and config: align stage types and add the new keys.**
- Acceptance: the schema `type` enum contains every neutral `StageKind` value (`build`
  included); `build.commands.build` exists with per-preset defaults (D12); the gate default of a
  `custom` stage is one documented value in both config lanes; legacy values (`integration-test`, `plan`, `docs`, `release`) still load with a
  documented mapping and a warning; `execution`, `run.*`, `observe.*` exist with the rules in 03
  (mutual exclusion, commands only from `build:` for the baseline stages, mandatory
  `observe.producer`, secret-name pattern, no name of a Stagr-used credential or reserved platform
  prefix); secret
  values are never echoed in errors.
- Test: `validate_config.py` and `test_cli.py` cases for each rule, including a mutant that
  drops each rule and must be caught.

**I2. Core: native-outcome interpretation.**
- Acceptance: one pure function maps a neutral native outcome plus attempt data to
  `(state, conclusion, reason)` exactly as table 02; attempt-lineage rules and `PASS`-final (D9); head
  binding; no platform words in the module; conformance vector groups V-N, V-H, V-A committed.
- Test: `test_neutral_core_models.py` runs every vector; a mutation of any table row fails a test.

**I3. Core: capability descriptor and refusal rules.**
- Acceptance: the capability declaration (05, eight questions) is a typed structure; GitHub
  declares it; rendering a blocking managed stage is refused when required capabilities are
  missing; `definition_source = pr_branch` produces a warning and makes empty `protected_paths` an
  error; the new neutral modules contain no platform names.
- Test: unit tests with a fake platform that lacks each capability in turn; a denylist test over
  the *new* neutral modules only (existing modules already name GitHub-specific concepts such as
  `CHECK_RUN`, so a repository-wide grep would be brittle).

### P2 Runtime rule

**I4. Dependents wait on a recoverable upstream failure (D8).**
- Acceptance: every non-`PASS` upstream (including state `FAILED`) leaves the dependent waiting
  with a reason; a re-run that turns green wakes the dependent; a wake-up never starts a stage
  that already has a `RUNNING` or `COMPLETED` result for the head; existing review-stage behaviour
  is otherwise unchanged and every removed `FAILED` propagation is listed in the pull request;
  vector group V-D committed.
- Test: strict fake-CLI behavioural tests for red, fixed, transient-error and never-fixed
  upstream, and for repeated wake-ups; governance interop unchanged.

### P3 GitHub managed check stage

**I5. Restructure the GitHub stage workflow into eligibility, work and publish jobs for a managed check stage.**
- Acceptance: security rules S1 to S14 hold in the rendered artifact; the work job has a read-only,
  non-persisted token, no secrets unless declared, mandatory timeout, its own cancel-superseded
  group; publish holds the credential, never checks out code, runs `always()` and is the only
  Check Run creator; the published result follows table 02 including the fail-closed inversion
  of today's mapping (cancelled publishes `FAILED`; only `success` passes); the work job writes
  `RUNNING` before executing; hostile commands and branch names are inert; all third-party
  actions are pinned; superseded runs cannot publish for a stale head; managed stages refuse
  forks.
- Test: render-structure tests for every rule; behavioural tests with the fake CLI for
  success, failure, timeout, cancelled, skipped, re-run, moved head; interop with the real merge
  gate; actionlint clean; mutation checks results in the PR.

### P4 Init, plan, apply, doctor

**I6. Generate and validate check stages from `build:`.**
- Acceptance: `stagr init` writes `build` and `unit-test` as blocking stages wired per D4 and
  commented command placeholders; `plan`/`apply` render them; `doctor` reports missing commands
  (blocking stage with nothing to run), drift between config and rendered files, capability
  refusals, protected-path changes (D3), and deprecations.
- Test: end-to-end CLI tests init to plan to apply to doctor for three presets; each doctor
  message has a positive and a negative test.

### P5 Observed stages

**I7. Read a named result from an existing CI or service.**
- Acceptance: an observed stage passes only when a result with the configured name exists for the
  current head, is authored by the configured producer identity, and is `success`; wrong
  producer, duplicate producers, missing, stale, skipped, neutral, cancelled do not pass;
  a shared CI identity is refused for a blocking observed stage unless the definition comes from the
  trusted base (05); the wake-up path from the foreign result's completion event is defined and
  tested, with the sweep-cannot-create limitation documented; optional timeout ends in state
  `FAILED`; vector group V-O committed.
- Test: fake-CLI behavioural tests for every vector row; interop with the merge gate.

**I8. `modules.sonar` becomes a deprecated alias.**
- Acceptance: `doctor` warns and prints the equivalent observed stage; declaring both is an
  error; existing V1 behaviour is unchanged for repositories that keep the alias.
- Test: CLI tests for alias-only, both, and observed-only configs; governance interop shows the
  V1 behaviour is preserved.

### P6 Platform author kit

**I9. Conformance vectors packaged and documented.**
- Acceptance: vectors are loadable by any renderer test suite; a short "adding a platform" page
  covers the capability descriptor, the vectors, and the mapping table; the mapping table is
  fact-checked against vendor documentation for GitLab, Azure DevOps, Bitbucket and Jenkins
  (each cell marked verified or removed).
- Test: the GitHub runtime and the neutral reference both run the packaged vectors in CI; a
  documentation check confirms every capability in code is described on the page.

### P7 Dogfood

**I10. This repository builds and tests itself through Stagr.**
- Acceptance: `build` and `unit-test` stages run this repository's existing four checks; run in
  parallel with the current `Validate` workflow on at least five pull requests, with every
  difference in outcome recorded and explained (identical outcomes are not assumed); the
  foundation auto-merge gate, which today requires the `Validate` check from the trusted workflow
  and does not read Stagr stage results, is changed in its own security-reviewed pull request to
  require them; then the required checks are swapped by a repository administrator.
- Test: a comparison record in the pull request; on a throwaway branch, a deliberately broken
  commit turns `unit-test` red and the foundation gate refuses; a fix turns it green and the gate
  accepts.

Documentation for each item ships **with** that item (`CONFIGURATION.md`, `ARCHITECTURE.md`,
`CLI.md`, and the platform-authors page), not as a separate phase.

## Existing documents to amend as phases land

| Document | Change | Phase |
|---|---|---|
| `05-governance-and-trust.md` | External gates: mark V1 fail-open as deprecated, point to observed stages | I8 |
| `08-github-codex-mapping.md` | Dependency rule for recoverable failures; check-stage mapping section | I4, I5 |
| `02-canonical-stage-model.md` | Execution modes (managed and observed) for check stages | I1 |
| `07-validation.md` | New doctor checks | I6 |

## Risks

| Risk | Mitigation |
|---|---|
| Config grows into a second CI language | Non-goals in 01; the key list in 03 is closed; richer needs use observed mode |
| Platform words leak into the core | Capability descriptor (05); the automated keyword test (I3) |
| Weaker platforms cannot meet S4 | Made visible by the descriptor; protected paths (04); advisory-only fallback |
| Dependency and outcome-mapping changes regress review stages | I4 and I5 are covered by the existing behavioural suite plus new cases; every removed propagation is listed in the pull request |
| Repository CI and Stagr results disagree during migration | Side-by-side run with a recorded comparison; the old gate stays until the new one is proven (I10) |
| Runner cost and latency of running builds | Timeouts, cancel-superseded, reviews waiting for `build` (D4), per-stage opt-out |
| Vendor documentation drifts | Mapping cells marked "verify" until confirmed; re-verified before a platform renderer is built |
| Review cycle drags on | One PR, small documents, reviewers state per-document approval; unresolved items are recorded as decisions |

## What reviewers should check (per document)

| Doc | Focus |
|---|---|
| 01 | Are goals and non-goals right? Do the baseline and blocking/advisory meanings match the intended policy? |
| 02 | Is every native outcome mapped safely? Is the two meanings of "failed" clear? |
| 03 | Is the config the smallest that works? Any key that should not exist, or is missing? |
| 04 | Any threat missing? Any rule that cannot actually be met? |
| 05 | Is anything platform-specific in the neutral parts? Are the mapping claims accurate? |
| 06 | Does the merge gate still hold? Is the dependency amendment safe? |
| 07 | Is the test strategy enough to prove neutrality and security? |
| 08 | Are the items independent, ordered, and testable? Are the decisions right? |

## Definition of done for this plan

1. Code review and security review have completed on the current head and every finding is fixed
   or declined with evidence.
2. No unresolved review thread remains.
3. D1 to D13 are confirmed or changed in this document.
4. Then the pull request is merged and issues I1 to I10 are created, each copying its
   acceptance criteria and test item.
