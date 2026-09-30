# Onboarding & config — org-scoped setup and versioning

stagr should be a **one-time configuration**, not a per-repo chore. This page defines how a repo (or
a whole org) is onboarded and how the config is versioned.

> **Status.** Today the only onboarding step stagr performs is per repo: `stagr plan` and
> `stagr apply` turn `.agentic/config.yml` into workflow files ([`../CLI.md`](../CLI.md)). The
> org-level setup described below is design, tracked in issues #87 (app installation), #91
> (org secrets), #94 (injected workflows), #96 (org rulesets), #106 and #109 (`init` and org
> defaults).

## Goal: set up once at the org, not per repository

The win is that integrating a new repo needs **no fresh setup**. The apps, secrets, pipeline and
gate are already provisioned at the org or project level, and the repo only declares what is
genuinely its own.

### One-time at org / project level

| Concern | How it is one-time |
|---|---|
| **App installation + config** | The agent apps (Codex, Claude) are installed once at the org, for all or selected repos. **Installation alone is not enough for the Codex review process this repository runs.** The Codex App must be set to run only the **code** review automatically when a PR opens, because `request-codex-review-on-push.yml` requests a code review on pushes (not on PR open) and `request-final-security-review.yml` is the only trigger of the security review. If the App also runs its own security review on open, it races the code review and a PR can get concurrent reviews. |
| **Secrets & environment** | Org or environment secrets are shared to selected repos, so there is no per-repo secret setup ([security-and-secrets.md](security-and-secrets.md)). |
| **The pipeline** | Org **required or reusable workflows** are injected centrally, so a repo needs no copied-in workflow files. |
| **The gate** | Org **rulesets** enforce branch protection and required checks across repos from a place a repo or PR cannot edit. They **must enable "dismiss stale approvals on push"**: GitHub does not invalidate an approval on a new push by itself, so without the setting a stale approval can carry a changed head into merge ([trust-and-correctness.md](trust-and-correctness.md#anti-tamper--enforcement)). |

### Irreducibly per-repo

Some things are genuinely repo-specific and cannot be fully centralized:

- **Build and test commands**: a repo's definition of "green". This is designed in
  [design-docs/09-check-stages.md](../../design-docs/09-check-stages.md); the config does not read
  it yet.
- **Which optional stages** the repo opts into and any per-repo overrides.

**Workflow-file setup today:** each repo runs `stagr apply` and the operator **commits the written
workflow files into that repo**, so committing generated workflow files is a per-repo step.
Org-injected workflows, which would remove it, are not built. There is no per-repo agent or key
setup when apps and secrets are provisioned at the org level.

## Config layering: org default + per-repo override

The contract has **no layering today**. A repo's `.agentic/config.yml` is its whole config, and an
unknown top-level key such as `extends` is ignored (`stagr/core/config_validation.py` validates only
the keys in `stagr/config.schema.json`). The design intent is an org, team and repo layering, so a
repo overrides **only** what differs:

- The org sets the standard stage graph, gate and policies once.
- A repo overrides only its specifics (for example an extra custom stage).
- Deleting an override falls back to the base, so the common repo overrides **nothing**.

The base must be **present in the repo's checkout**, so the design does not rely on fetching remote
bases. It would reach a repo in one of two ways:

- **Vendoring** the org base into the repo, refreshed by the provisioning step; or
- **Injection** by an org required or reusable workflow that supplies the base at render time.

A **live** org default (edit once at the org and every repo picks it up without re-vendoring) would
need a provisioning re-sync step or an authenticated resolver.

## The onboarding CLI

[`../CLI.md`](../CLI.md) is the command reference. The commands that exist are `stagr help`,
`stagr plan` and `stagr apply`.

- **`stagr plan`** is a dry run: it lists exactly the files `apply` would write, with sizes and
  hashes, and writes nothing.
- **`stagr apply`** writes those same files into the working tree. The operator then **commits the
  generated files and opens their own PR**. `apply` performs no Git or GitHub action itself, never
  hand-merges and never deletes files. Both commands run one shared pipeline
  (`stagr/cli/render_pipeline.py`), so they cannot disagree.
- **`stagr init`** (planned) proposes a starting `.agentic/config.yml` and asks for the GitHub App
  ID.
- **`stagr doctor`** (planned, issue #203) reports whether a repo is ready to run the generated
  pipeline. It is designed in [`../../design-docs/doctor/README.md`](../../design-docs/doctor/README.md).

## Config versioning

- The schema is **versioned** and a config declares its version. Only **version 2** is accepted;
  any other value is rejected before anything is rendered.
- `validate_config` (`stagr/core/config_validation.py`) is the single front door for config
  validation: the schema, the publisher block, normalization (profile, stage ids, dependencies and
  cycles, provider and backend resolution) and the skill files. CI's
  `.github/scripts/validate_config.py` calls it rather than a second implementation.

## Language & platform agnosticism

- **Language-agnostic:** the contract never names a language or SDK. How a repo declares "green" is
  designed in [design-docs/09-check-stages.md](../../design-docs/09-check-stages.md).
- **Platform-agnostic by contract:** `platform.type` selects the renderer. GitHub is the only
  renderer today; another platform means adding a renderer, not changing the contract.

## What "onboarded" means here

Onboarded means: the org's apps, secrets, workflows and rulesets are provisioned once; a new repo is
covered by the org default with at most a tiny override; and `stagr doctor` reports the repo as
ready (schema valid, models resolvable, secrets present, gate enforced).
