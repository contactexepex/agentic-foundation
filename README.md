# agentic-foundation

A reusable toolkit that drops a configurable **graph of SDLC/STLC agent stages** — plan, implement,
security, test, review, and more — into *any* repository, on *any* SCM platform, in *any* language,
with *any* provider/model per stage. It is the generic engineering core extracted from the
`permission-api` project, with everything product-specific (Azure deploy, the runtime app, the
Permission-API domain) removed.

After a small, one-file configuration step, a target repository gets an agentic pipeline: each stage
is an AI agent bound to the provider, model, and backend you choose; stages gate on CI; and a pull/
merge request is opened for human review.

## What it is (and is not)

- **Is:** a platform-neutral **config contract** + a deterministic installer/CLI + per-platform
  renderers + pluggable agent backends + a Claude Code skill front door. Provider-, model-,
  platform-, and language-agnostic.
- **Is not:** an agent (it *composes* mature OSS agents), a deployment system, a runtime, or anything
  tied to one language, one AI vendor, or one Git host.

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the design and
**[docs/LANDSCAPE.md](docs/LANDSCAPE.md)** for how it differs from existing tools.

## Flexible by design

**Stages are agents; anything plugs in.** A pipeline is an ordered, extensible graph of stages. Each
stage binds a **role/type** (plan, implement, security, test, integration-test, review, docs, …) to a
**provider + model** and a **backend** — so any permutation works:

| Stage | Provider | Model | Backend |
|---|---|---|---|
| implement | claude | `strong` (alias) | `claude-code-action` |
| security | openai | `complex` tier | `generic` |
| review | gemini | `balanced` | `pr-agent` |
| integration-test | — | — | `generic` |

Same provider with different models, multiple providers, or any frontier-model mix — all per stage.

**Models are configurable, layered, and dynamic.** You need not specify a model at all: each stage
resolves one through a precedence chain — **per-request override › stage model › org/account
default** (then it fails loudly if unresolved — no hidden fallback) — so *providing a model overrides
the default*, and omitting it inherits.
Optionally enable **tiering**: a trivial change runs on a low-cost model, a large/complex one
escalates — selection is **deterministic** (change-size + path signal), no extra model call. See
[Model resolution](docs/CONFIGURATION.md#3a-model-resolution).

**Any platform.** `platform.type` (github | gitlab | azure_devops | bitbucket | gitea) selects a
renderer that maps the same contract to that system (PR↔MR, roles, required checks). GitHub ships
first; others follow.

**Compose, don't reinvent.** A stage's `backend` wraps a mature OSS agent (OpenHands, PR-Agent,
claude-code-action, Codex, SWE-agent) or the built-in `generic` runner — adopt one per stage without
touching the rest.

**Skills + agents catalog.** Reusable **skills** (methodology: checklist, rubric, output format —
provider/backend/language-agnostic) are the content; **agent presets** wire a skill to a stage. Ships
with `code-review` and `security-review` skills + presets; drop one in with `from: code-review` and
override only what you need, or register/override your own by id. See
[skills & agents](docs/ARCHITECTURE.md#3a-skills-and-agents--content-vs-wiring).

**Simple by default, advanced when you want it.** A runnable config is a `version`, a `profile`
(`minimal`/`standard`/`full`, which expands to a default stage graph), a `platform`, and a model
binding (`defaults.models.<provider>`, or a per-stage model) — model resolution is fail-loud, so
there is no hidden default. That is still just a few lines; define `stages` only for finer control.

**Secrets stay secret.** The toolkit never logs, prints, or exposes any credential (API key, token,
username, or password), never stores them, and keeps them out of `.agentic/config.yml` — see
[Secret handling](docs/CONFIGURATION.md#3b-secret-handling-non-negotiable).

**Everything adapts to your setup — nothing hardcoded.** All of the following are optional and
configurable, so an org, team, or individual can bend the toolkit to how they deploy, host, and
observe:

- **Profiles** (`minimal`/`standard`/`full`) — expand to a default stage graph; override any part.
- **Config inheritance** (`extends`) — layer an org base → team base → repo; local values win.
- **Model aliases** — reference `fast`/`balanced`/`strong` (your names) and map IDs per provider.
- **Custom / self-hosted providers** — `base_url`, API version, deployment, and the *name* of the key
  secret (Azure OpenAI, Vertex, proxies, on-prem gateways). Any provider id.
- **Cost & token budgets** — per-run/per-period caps, global or per-stage; `block`/`downgrade`/`warn`.
- **Prompt-injection guardrails** — treat PR/issue/comment/diff content as data, not instructions.
- **Observability** — run records to a file, CI artifact, webhook, or OTLP collector; endpoints from a
  variable/secret *name*, never hardcoded; secrets always redacted.
- **`doctor` & `plan`** — validate config + secrets and dry-run before anything is applied.

**Secrets stay secret.** Never logged, printed, stored, or placed in config — see
[Secret handling](docs/CONFIGURATION.md#3b-secret-handling-non-negotiable).

**Language-agnostic.** A repo declares what "green" means (`install`/`lint`/`test`/`typecheck`) via a
preset (`python`, `maven`, `gradle`, `node`, `go`, `rust`, `dotnet`) or custom commands. Stages never
assume a language.

## Modules

- **core** (always): renders the enabled stage graph + deterministic routing/tiering + review-thread
  hygiene. Humans merge.
- **+auto_merge** (opt-in, off by default): the fail-closed foundation auto-merge gate.
- **+sonar** (opt-in): SonarQube/SonarCloud quality gate as a required check.

## Quickstart

> **Status:** the renderer (M2) and the one-command CLI (`doctor`/`plan`/`apply`, M3) and front-door
> skill (M4) are **not shipped on `main` yet** — see the roadmap. Until then, follow the manual flow
> below; step 3's "Planned" note describes the intended automated experience.

1. In your target repo, add `.agentic/config.yml` (copy `templates/config/agentic.config.yml.tmpl`
   and edit it — set a `profile` and `platform`).
2. Create the secrets your stages/providers and platform require — see
   [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for names and service-account vs PAT guidance.
3. **Today (manual):** hand-adapt the automation you need. The workflows in this repo's
   `.github/workflows/` are the toolkit's *own* pipeline — e.g. `validate.yml` runs
   `validate_config.py` against *this* repo's contract tree — so they are references to adapt, **not
   files to copy verbatim** into a target repo (a verbatim copy would fail CI on the missing
   validator). There is no standalone target-repo config validator until the renderer/CLI land.
   **Planned (M2/M3):** the renderer generates your `.github/workflows/` from `.agentic/config.yml`,
   and `agentic doctor` / `agentic apply` validate the config and install the pipeline for you.
4. Merge it. The pipeline is live.

Full field reference, provider→secret mapping, and troubleshooting:
**[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**.

## Layout

```
templates/skills/<id>/           reusable skill methodologies (code-review, security-review, ...)
templates/agents/<id>.yml        pre-wired agent presets that reference a skill
templates/config/                the .agentic/config.yml template
install/                         config.schema.json, modules.yml
docs/                            ARCHITECTURE.md, CONFIGURATION.md, LANDSCAPE.md
.github/workflows/               this repo's live automation (reference impl for the renderer)
.github/scripts/                 validate_config.py + docs
.agentic/config.yml              this repo's own agentic contract (dogfood)

# Planned (see ARCHITECTURE.md roadmap):
templates/workflows/<platform>/  per-platform pipeline templates (M2; github first)
templates/contract/              AGENTS.md / CLAUDE.md skeletons (M2)
templates/presets/               per-ecosystem command presets (M2)
install/ (installer/CLI)         doctor / plan / apply (M3)
skill/                           the Claude Code front-door skill (M4)
```

## Dogfooding

This repository runs the pattern on itself. `.agentic/config.yml` is its declarative source of truth,
and `.github/workflows/` are the hand-written **reference implementation** the M2 GitHub renderer will
later generate:

- **Claude implements** (`claude-code-implementor.yml`, manual dispatch) and **Codex implements**
  (`authorized-engineering-task.yml`, on the `codex-engineering` issue label) via an
  untrusted-implement → validate → trusted-publish (remediation) flow.
- **Codex reviews** — code and security — is re-requested on every push
  (`request-codex-review-on-push.yml`); the deterministic router (`fast-ai-code-review.yml`)
  fast-paths trivial docs changes.
- **`Validate`** (`validate.yml`) is the CI gate; **fixed Codex threads auto-resolve**
  (`resolve-fixed-codex-review-threads.yml`); the **fail-closed foundation gate**
  (`auto-merge-foundation-prs.yml`) merges provably-ready PRs. Humans keep authority via `human-merge`.

> Status: **M1 — contract layer (v2), now dogfooded.** Platform-neutral stage-graph schema, profiles,
> provider/model resolution, backends, cross-cutting policy, and the toolkit's own live Claude+Codex
> automation are in place. Next: templatize these workflows into `templates/workflows/github/` and
> build the generic backend + installer/CLI (see [ARCHITECTURE.md](docs/ARCHITECTURE.md) roadmap).
