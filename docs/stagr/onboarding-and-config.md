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
| **App installation + config** | When the configuration includes OpenAI review or security stages (the default profile does; a custom graph with no OpenAI stages needs no App), the **Codex App** is installed once at the org, for all or selected repos (the Claude Code integration needs no GitHub App — it runs via `ANTHROPIC_API_KEY`). **Installation alone is not enough:** the Codex App must be **configured to auto-run the code review on PR open** when the review stage includes `pr_opened` in its `triggers`, or when `triggers` is absent (defaults to `pr_opened` + `pr_updated`); it must also have its **native security auto-review disabled** to prevent racing the final-security workflow. Miss either applicable setting and a PR can go unreviewed or get concurrent code+security reviews. |
| **Secrets & environment** | Org/environment secrets shared to selected repos — no per-repo secret setup ([security-and-secrets.md](security-and-secrets.md)). |
| **The pipeline** | Org **required/reusable workflows** injected centrally, so a repo needs no copied-in workflow files. |
| **The gate** | Org **rulesets** enforce branch protection + required checks across repos from a place a repo/PR cannot edit, and **must enable "dismiss stale approvals on push"** so a post-approval commit invalidates the prior human approval (this is what makes the human-lane re-approval rule real — see [edge-cases.md](edge-cases.md)). ([trust-and-correctness.md](trust-and-correctness.md#anti-tamper--enforcement)) |

### App installation at the org level

When your configuration includes a Codex review or security stage (the default profile includes
both; a custom graph with no OpenAI stages needs no App), the **Codex App** must be installed once at
the org level. Installing it at the org grants access to all current and future repos in the org;
you can restrict the grant to selected repos instead, but any unselected repo will not be covered.
The Claude Code integration uses `anthropics/claude-code-action` with `ANTHROPIC_API_KEY` — no
GitHub App install is needed for it.

**Where to install:**

- **Codex App** — install from the GitHub Marketplace listing for Codex. During installation,
  under "Repository access", choose "All repositories" or select the repos stagr will manage.

Install once at the org, not per repository. If a new repo needs coverage later, expand the
installation's repository access list — no other per-repo step is needed for app access.

#### Required Codex App configuration

Installation alone is not enough. After installing the Codex App, two settings must be configured:

**1. Auto-run code review on PR open**

Enable the setting that triggers Codex to start a code review automatically when a PR is opened.
This setting is required when the Codex review stage includes `pr_opened` in its `triggers`, or
when `triggers` is absent (absent `triggers` defaults to both `pr_opened` and `pr_updated`; the
default profile falls into this case); stages configured with only `pr_updated` or `manual` triggers
do not rely on the App's open trigger.

- *Where:* Codex App settings → code review behaviour → enable "Run automatically on pull request
  open".
- *Why it is required:* the rendered `request-review.yml` workflow listens to
  `pull_request_target: synchronize` events; it does not fire on the initial `pull_request: opened`
  event. A freshly opened PR therefore relies on the Codex App's own trigger to start the first code
  review.
- *Failure mode if missing:* a brand-new PR receives no code-review pass until someone pushes a
  follow-up commit. When `modules.auto_merge: true` and the Codex review stage is blocking, the
  auto-merge gate requires a head-bound Codex code review before it merges, so the PR will stall at
  the gate and never auto-merge, even if all CI is green.

**2. Native security auto-review disabled**

Disable the Codex App's built-in security auto-review feature.

- *Where:* ChatGPT/Codex cloud settings → navigate to
  `https://chatgpt.com/codex/cloud/settings/general` → security review → disable "Run security
  review automatically".
- *Why it is required:* stagr serializes code review and security review through dedicated
  workflows: `request-review.yml` handles code review per push, and
  `final-security-review.yml` fires the security review only after code review has converged
  on the head commit. The Codex App's native security auto-review runs independently and
  concurrently with that sequencing.
- *Failure mode if missing:* the Codex App fires a security review at the same time as — or before —
  the code-review loop has finished. This produces concurrent code and security reviews, which
  violates the ordered-gate invariant; the Codex backend errors on concurrent reviews, resulting in
  a missing or failed head-bound review signal. When `modules.auto_merge: true` and the Codex
  security stage is blocking, this can strand the merge gate.

No other app requires post-install settings changes for stagr's default configuration.

### Irreducibly per-repo (stated honestly)

Some things are genuinely repo-specific and cannot be fully centralized:

- **Build/test commands** — a repo's definition of "green" (`build.commands`).
- **Which optional stages** that repo opts into (integration/perf/custom) and any per-repo
  overrides.

**Workflow-file setup today [shipped]:** each repo currently runs `stagr apply` to write the rendered
workflow files and the operator **commits them into that repo** — so committing generated workflow
files *is* a per-repo step today. Removing it via **org-injected required/reusable workflows** (so no
workflow files live in the repo) is **[target]** (Phase 2). There is no per-repo **agent or key**
setup when apps/secrets are provisioned at the org level.

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

See [`../CLI.md`](../CLI.md) for the authoritative command reference; in summary:

- **`stagr init`** — autodetect the build toolchain and propose a starting `.agentic/config.yml`
  (guided wizard or `--profile`).
- **`stagr doctor`** — a **local, read-only, secret-free** health report: it resolves the config,
  reports **resolvable models** and the **secret NAMES** the pipeline needs, and renders the
  workflows. It does **not** probe the environment — it does **not** check whether those secrets
  actually exist, or whether the merge gate/ruleset is installed. Verifying secrets and rulesets is a
  **manual** onboarding step today; automated environment probes are **[target]**.
  - **Known gap [target]:** for an implement stage, `doctor` reports the configured
    `providers.anthropic.api_key_secret` name, but the shipped `implementor.yml` **hardcodes
    `ANTHROPIC_API_KEY`**. Overriding that secret name today leaves the rendered job **without its
    credential even though `doctor` succeeds** — use the default name until the resolved name is
    wired into the template.
- **`stagr plan`** — dry run: show exactly what `apply` **would** write to `.github/workflows/`
  (with `--diff`), marking each workflow.
- **`stagr apply`** — **writes the rendered workflow files into `.github/workflows/` in the working
  tree**; orphaned workflows are removed **only with `--prune`** (by default they are kept). The
  operator then **commits the generated files and opens their own PR**. `apply` performs **no Git or
  GitHub action itself** — there is **no auto-opened bootstrap PR** — and never hand-merges.

## Config versioning & migration

stagr is a contract, and contracts evolve (the `required_status_checks` shape already changed
once). With an org-default config feeding many repos, an unversioned schema would break everyone on
upgrade. Therefore:

- **[shipped]** The schema is **versioned** and a config declares its version; today the schema
  accepts **only version 2**, and any other version fails validation with the generic schema error.
- **[target]** An explicit **compatibility range**, a **migration command/path** for breaking
  changes, and **`doctor` migration guidance** ("your config targets vN; this release wants vN+1")
  are **not implemented yet** ([roadmap.md](roadmap.md)).
- **[shipped]** Render-time validation is the single front door — `stagr.render.validate_config()`
  (schema → coherence → templating safety); CI's `validate_config.py` calls it, not a second
  implementation.

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
