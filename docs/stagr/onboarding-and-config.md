# Onboarding & config — org-scoped setup, override, and versioning

stagr must be a **one-time configuration**, not a per-repo chore. This page defines how a repo (or
a whole org) is onboarded, how config layers, and how the config is versioned.

## Goal: set up once at the org, not per repository

The win is that integrating a new repo requires **no fresh setup** — the apps, secrets, pipeline,
and gate are already provisioned at the org/project level, and the repo only declares what is
genuinely its own.

### One-time at org / project level

| Concern | How it is one-time |
|---|---|
| **App installation + config** | The agent apps (Codex, Claude) are installed once at the org, for all or selected repos. **Installation alone is not enough:** the Codex App must be **configured to auto-run the code review on PR open** (the review-request workflow (`request-codex-review-on-push.yml` in this repository) listens to pushes, not PR-open events, so a freshly opened PR relies on the App to start the code review), and its **native security auto-review must be disabled** so it does not race the final-security workflow. Miss either and a PR can go unreviewed or get concurrent code+security reviews. |
| **Secrets & environment** | Org/environment secrets shared to selected repos — no per-repo secret setup ([security-and-secrets.md](security-and-secrets.md)). |
| **The pipeline** | Org **required/reusable workflows** injected centrally, so a repo needs no copied-in workflow files. |
| **The gate** | Org **rulesets** enforce branch protection + required checks across repos from a place a repo/PR cannot edit, and **must enable "dismiss stale approvals on push"** so a post-approval commit invalidates the prior human approval (this is what makes the human-lane re-approval rule real — see [edge-cases.md](edge-cases.md)). ([trust-and-correctness.md](trust-and-correctness.md#anti-tamper--enforcement)) |

### Irreducibly per-repo (stated honestly)

Some things are genuinely repo-specific and cannot be fully centralized:

- **Build/test commands** — a repo's definition of "green" (designed in
  [design-docs/09-check-stages.md](../../design-docs/09-check-stages.md); the config does not read it
  yet).
- **Which optional stages** that repo opts into (integration/perf/custom) and any per-repo
  overrides.

**Workflow-file setup [shipped]:** each repo runs `stagr apply` to write
the rendered workflow files and the operator **commits them into that repo** — so committing
generated workflow files *is* a per-repo step. Removing it via **org-injected required/reusable workflows** (so no
workflow files live in the repo) is **[target]** (Phase 2). There is no per-repo **agent or key**
setup when apps/secrets are provisioned at the org level.

## Config layering: org default + per-repo override — **[target]**

Stagr does not layer config today: a repo's `.agentic/config.yml` is its whole config. The design
target is an org → team → repo layering, so a repo overrides **only** what differs:

- The org sets the standard stage graph, gate, and policies once.
- A repo overrides only its specifics (an extra custom stage).
- Deleting an override falls back to the base; the common repo overrides **nothing**.

**How the org default would reach a repo (be precise).** The base must be **present in the repo's
checkout**, so the design does not rely on fetching remote bases. It would be delivered by one of:

- **Vendoring** the org base into the repo, refreshed by the onboarding/provisioning step; or
- **Injection** via an org **required/reusable workflow** that supplies the base at render time.

A **centrally-updated, live** org default (edit once at the org, every repo picks it up without
re-vendoring) needs a provisioning re-sync step or an authenticated resolver
([roadmap.md](roadmap.md)).

## The onboarding CLI

See [`../CLI.md`](../CLI.md) for the authoritative command reference. **Today the commands are
`stagr help`, `stagr plan` and `stagr apply`.** `init` and `doctor` are **[target]**, being rebuilt on the neutral core:

- **`stagr init`** — a later step: propose a starting `.agentic/config.yml`, and ask for the GitHub
  App ID.
- **`stagr doctor`** (issue #203) — a **local, read-only, secret-free** health report: it validates
  the config and lists the **secret NAMES** the pipeline needs. It will **not** probe the
  environment — it will not check whether those secrets actually exist, or whether the merge
  gate/ruleset is installed. Verifying secrets and rulesets is a **manual** onboarding step;
  automated environment probes are **[target]**.
- **`stagr plan`** **[shipped]** — dry run: list exactly the files `apply` **would** write, with
  sizes and hashes. Writes nothing.
- **`stagr apply`** **[shipped]** — **writes those same files into the working tree**. The operator
  then **commits the generated files and opens their own PR**. `apply` performs **no Git or GitHub
  action itself** — there is **no auto-opened bootstrap PR** — and never hand-merges. It never
  deletes files; removing files that are no longer rendered will be its own story. Both commands run
  one shared pipeline (`stagr/cli/render_pipeline.py`), so they cannot disagree.

## Config versioning

- **[shipped]** The schema is **versioned** and a config declares its version; today the schema
  accepts **only version 2**, and any other version fails validation with the generic schema error.
- **[shipped]** `validate_config` (`stagr/core/config_validation.py`) is the single front door for
  config validation: schema → publisher block → profile → dependency references and cycles →
  provider/backend resolution → skill files. CI's `.github/scripts/validate_config.py` calls it, not
  a second implementation.

## Language & platform agnosticism

- **Language-agnostic:** the contract never names a language or SDK. How a repo declares "green" is
  designed in [design-docs/09-check-stages.md](../../design-docs/09-check-stages.md).
- **Platform-agnostic by contract:** `platform.type` selects the renderer. GitHub ships first;
  other renderers are added without touching the contract ([roadmap.md](roadmap.md)).

## What "onboarded" means here

Onboarded means: the org's apps/secrets/workflows/ruleset are provisioned once; a new repo is
covered by the org default with at most a tiny override; and `stagr doctor` (planned) reports the
repo as ready (schema valid, models resolvable, secrets present, gate enforced).
