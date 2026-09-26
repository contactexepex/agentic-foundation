# Onboarding & config — org-scoped setup, override, and versioning

stagr must be a **one-time configuration**, not a per-repo chore. This page defines how a repo (or
a whole org) is onboarded, how config layers, and how the contract evolves without breaking
adopters.

## Goal: set up once at the org, not per repository

The win is that integrating a new repo requires **no fresh setup** — the apps, secrets, pipeline,
and gate are already provisioned at the org/project level, and the repo only declares what is
genuinely its own.

### One-time at org / project level

| Concern | How it is one-time |
|---|---|
| **App installation** | The agent apps (Codex, Claude) are installed once at the org, for all or selected repos. |
| **Secrets & environment** | Org/environment secrets shared to selected repos — no per-repo secret setup ([security-and-secrets.md](security-and-secrets.md)). |
| **The pipeline** | Org **required/reusable workflows** injected centrally, so a repo needs no copied-in workflow files. |
| **The gate** | Org **rulesets** enforce branch protection + required checks across repos from a place a repo/PR cannot edit, and **must enable "dismiss stale approvals on push"** so a post-approval commit invalidates the prior human approval (this is what makes the human-lane re-approval rule real — see [edge-cases.md](edge-cases.md)). ([trust-and-correctness.md](trust-and-correctness.md#anti-tamper--enforcement)) |

### Irreducibly per-repo (stated honestly)

Some things are genuinely repo-specific and cannot be fully centralized:

- **Build/test commands** — a repo's definition of "green" (`build.commands`).
- **Which optional stages** that repo opts into (integration/perf/custom) and any per-repo
  overrides.

There is **no per-repo agent, key, or workflow-file setup** — only this small, genuinely-local
declaration.

## Config layering: org default + per-repo override

stagr layers config **org → team → repo** via `extends`, so a repo overrides **only** what differs:

- The org sets the standard stage graph, gate, budgets, and policies once.
- A repo overrides only its specifics (build/test commands, an extra custom stage).
- Deleting an override falls back to the base; the common repo overrides **nothing**.

**How the org default actually reaches a repo (be precise).** `extends` **[shipped]** resolves
**local paths confined to the repository checkout only** — it **does not fetch remote/URI bases**
(those fail loudly). So a repo inherits an org default only by having that base **present in its
checkout**, delivered by one of:

- **Vendoring** the org base into the repo (referenced by relative path), refreshed by the
  onboarding/provisioning step; or
- **Injection** via an org **required/reusable workflow** that supplies the base at render time.

A **centrally-updated, live** org default (edit once at the org, every repo picks it up without
re-vendoring) is **[target]** — it needs a provisioning re-sync step or an authenticated resolver,
which the offline loader does not do today ([roadmap.md](roadmap.md)). This design does **not** rely
on remote `extends`.

## The onboarding CLI

- **`stagr init` / `doctor --init`** — detect language/build/platform and propose a starting
  `.agentic/config.yml` (or confirm the org default already covers the repo).
- **`doctor`** — validate config + environment (schema, resolvable models, required secrets present
  by name, gate/ruleset in place) and report gaps precisely. `doctor` runs locally and read-only.
- **`plan` / `apply`** — render the contract for the target platform and open the bootstrap PR;
  `apply` never hand-merges.

## Config versioning & migration

stagr is a contract, and contracts evolve (the `required_status_checks` shape already changed
once). With an org-default config feeding many repos, an unversioned schema would break everyone on
upgrade. Therefore:

- **The schema is versioned**, and a config declares the version it targets.
- **Compatibility is explicit** — a stagr release states which schema versions it accepts.
- **Migrations are provided** — a breaking schema change ships a migration path (and `doctor`
  reports "your config targets vN; this release wants vN+1: run the migration").
- **Render-time validation is the front door** — `stagr.render.validate_config()` (schema →
  coherence → templating safety) is the single validator; CI's `validate_config.py` calls it, not a
  second implementation.

## Language & platform agnosticism

- **Language-agnostic:** `build.commands` are the only definition of "green." The contract never
  names a language or SDK; stages run exactly the configured commands.
- **Platform-agnostic by contract:** `platform.type` selects the renderer. GitHub ships first;
  other renderers are added without touching the contract ([roadmap.md](roadmap.md)).

## What "onboarded" means here

Onboarded means: the org's apps/secrets/workflows/ruleset are provisioned once; a new repo is
covered by the org default with at most a tiny override; `doctor` reports the repo as ready
(schema valid, models resolvable, secrets present, gate enforced); and a schema upgrade has a
stated compatibility range and migration — no adopter is silently broken.
