# Build and Test Stages — Design Plan

**Status:** Proposal for review. No code changes. Nothing here is implemented yet.

This folder is the design plan for making **build**, **unit test** and other **CI-result
("check") stages** first-class, blocking stages of the Stagr pipeline — on any CI/CD platform,
not only GitHub. It is split into small documents so each can be reviewed on its own.

## The problem in one paragraph

Today only the two AI review stages (code review, security review) are real in the neutral
pipeline. A `build` or `test` stage renders a placeholder workflow that runs nothing. (The older
`python -m stagr.render` lane renders a single `Validate` job from `build.commands`, but that job
is not a stage: it publishes no Stagr result and is not neutral. This plan replaces it; see 07.) Yet the standard baseline for production
software is: **the code compiles, the unit tests pass, code review is done, security review is
done, and every review comment is resolved.** This plan closes that gap without breaking the
project's core rules: Stagr stays a control plane (it writes the wiring, the platform runs the
work), stays platform-neutral, and never lets untrusted code touch trusted credentials.

## Reading order

| # | Document | Question it answers |
|---|---|---|
| 01 | [Goals and principles](01-goals-and-principles.md) | What must be true, what is out of scope, which rules can never be broken? |
| 02 | [Check stage model](02-check-stage-model.md) | What is a check stage, how are results interpreted, what states exist? |
| 03 | [Config contract](03-config-contract.md) | What does the operator write? How small can it stay? |
| 04 | [Execution and security](04-execution-and-security.md) | Where does untrusted code run, and how is the result trusted? |
| 05 | [Platform neutrality](05-platform-neutrality.md) | How does one contract map onto GitHub, GitLab, Azure DevOps, Bitbucket, Jenkins? |
| 06 | [Orchestration and gating](06-orchestration-and-gating.md) | What runs when, what triggers what, and how does the merge gate use it? |
| 07 | [Extensibility, migration, testing](07-extensibility-migration-testing.md) | How do we add platforms and stage kinds, migrate, and prove it works? |
| 08 | [Delivery plan](08-delivery-plan.md) | Phases, issues with acceptance criteria and tests, open decisions, risks. |

## Vocabulary (used in every document)

- **Stage** — one step of the pipeline (from `02-canonical-stage-model.md`).
- **Review stage** — an AI reviewer; its findings are review threads. Already exists.
- **Check stage** — a stage whose result is a deterministic pass/fail produced by CI compute:
  build, unit test, integration test, performance test, SQL validation, SAST, DAST, dependency
  scan, or any custom check. **New in this plan.**
- **Managed** — Stagr renders the CI job that runs the work (the *work unit*).
- **Observed** — the team's own CI already runs the work; Stagr only reads the result.
- **Execution plane** — where the code under test runs (untrusted, no credentials).
- **Publication plane** — where the trusted result is written (holds the Stagr credential).
- **Native outcome** — what the CI platform itself reports (success, failure, cancelled, ...).
- **Producer identity** — who authored a piece of evidence (an app, a service account, a pipeline).
- **Head** — the newest commit of the pull request. Every result is bound to one head.

## How this plan gets accepted

1. This folder is reviewed as a pull request by the code and security reviewers.
2. Findings are fixed or declined with reasons, until the reviewers have no open findings.
3. Only then is the pull request merged (it carries the `human-merge` label until then).
4. After merge, the issues in [08](08-delivery-plan.md) are created from the plan, one per work
   item, each with acceptance criteria and a test item.

No implementation starts before step 3 is complete.
