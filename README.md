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
**provider + model**; the coding tool is derived from the provider — `anthropic` runs Claude Code,
`openai` runs Codex:

| Stage | Provider | Model | Tool (derived) |
|---|---|---|---|
| implement | anthropic | `strong` (alias) | Claude Code |
| review | openai | app-supplied | Codex |
| security | openai | app-supplied | Codex |

Mix Anthropic and OpenAI per stage, or vary the Anthropic model across stages. Today the toolkit
renders **Anthropic (Claude Code)** and **OpenAI (Codex)**; more providers/tools are roadmap and slot
in through the same provider→tool map without forking the contract.

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

**Compose, don't reinvent.** New tools plug in through one seam: a stage's optional `backend` override
wraps a mature OSS agent (OpenHands, PR-Agent, SWE-agent) or a custom adapter — roadmap today, added
without touching the rest. Normally you omit it and let the provider choose the tool.

**Skills + agents catalog.** Reusable **skills** (methodology: checklist, rubric, output format —
provider/backend/language-agnostic) are the content; **agent presets** wire a skill to a stage. Ships
with `code-review` and `security-review` skills + presets; drop one in with `from: code-review` and
override only what you need, or register/override your own by id. See
[skills & agents](docs/ARCHITECTURE.md#3a-skills-and-agents--content-vs-wiring).

**Simple by default, advanced when you want it.** A runnable config is a `version`, a `profile`
(`minimal`/`standard`/`full`, which expands to a default stage graph), and a `platform`. An
`anthropic` stage (Claude Code) also needs a model binding (`defaults.models.anthropic`, or a
per-stage model); an `openai` stage (Codex) supplies its own. Model resolution is fail-loud — no
hidden default. Still a few lines; define `stages` only for finer control.

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

1. **Install the CLI** (needs only Python 3.10+; see [docs/CLI.md](docs/CLI.md) for options). `stagr`
   is not on PyPI yet, so install it from the repository's source archive — pip/pipx download and
   build it with no `git` required:
   ```bash
   pipx install "https://github.com/contactexepex/agentic-foundation/archive/refs/heads/main.tar.gz"
   # once published this becomes: pipx install stagr
   ```
   For a reproducible, auditable install, pin the URL to a commit SHA (or a release tag) instead of
   `main` — see [docs/CLI.md](docs/CLI.md).
2. In your target repo, create `.agentic/config.yml` with **`stagr init`** — no hand-written YAML:
   ```bash
   stagr init                    # guided wizard (Enter accepts each default), or
   stagr init --profile standard # generate a commented config directly
   ```
   Profiles: `minimal` / `standard` / `full` / `custom`. `init` autodetects your build toolchain
   (Python, Node, Go, Maven/Gradle, Rust, .NET) and proposes the matching `build.preset` when the repo
   has the marker its commands need, else `custom`. See [docs/CLI.md](docs/CLI.md).
3. Validate and preview:
   ```bash
   stagr doctor                # validate the contract + list the secret NAMES to configure
   stagr plan                  # show exactly which files would be written to .github/workflows/
   ```
4. Create those secrets in your CI/SCM secret store (see [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
   for service-account vs PAT guidance), then render the pipeline:
   ```bash
   stagr apply                 # write .github/workflows/ from your contract
   ```
5. Commit and merge the rendered workflows.

> **What renders today:** the core lane — the `Validate` check, the review router, the Claude
> implementer, and (when a Codex review/security stage is configured) the Codex review + thread-cleanup
> lane. **Not yet rendered:** other stage types (`plan`, `test`, `integration-test`, `docs`, `release`,
> and non-Codex reviewers) **and the `modules` toggles** (`auto_merge`, `sonar`) — these are declared
> and validated but do not yet emit workflows; that rendering is on the roadmap
> ([docs/CHARTER.md](docs/CHARTER.md) §7). `stagr plan` always shows the exact set of files that will
> be written, so review it before committing.

Full field reference, provider→secret mapping, and troubleshooting:
**[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**.

## Layout

```
stagr/                                 the installable CLI package: cli.py, render.py,
                                       config.schema.json, backends/ (init / doctor / plan / apply)
stagr/templates/skills/<id>/           reusable skill methodologies (code-review, security-review, ...)
stagr/templates/agents/<id>.yml        pre-wired agent presets that reference a skill
stagr/templates/config/                the .agentic/config.yml template
stagr/templates/workflows/<platform>/  per-platform pipeline templates (github first)
stagr/templates/contract/              AGENTS.md / CLAUDE.md skeletons
pyproject.toml                         packaging for the `stagr` command
docs/                                  ARCHITECTURE.md, CONFIGURATION.md, CLI.md, CHARTER.md, LANDSCAPE.md
.github/workflows/                     this repo's live automation (reference impl for the renderer)
.github/scripts/                       validate_config.py + tests
.agentic/config.yml                    this repo's own agentic contract (dogfood)

# Planned (see ARCHITECTURE.md roadmap):
stagr/templates/presets/               per-ecosystem command presets
skill/                                 the Claude Code front-door skill (M4)
```

## Dogfooding

This repository runs the pattern on itself. `.agentic/config.yml` is its declarative source of truth,
and `.github/workflows/` are the hand-written **reference implementation** the GitHub renderer
(`stagr/render.py`) mirrors:

- **Claude implements** (`claude-code-implementor.yml`, manual dispatch) and **Codex implements**
  (`authorized-engineering-task.yml`, on the `codex-engineering` issue label) via an
  untrusted-implement → validate → trusted-publish (remediation) flow.
- **Codex reviews** — code and security — is re-requested on every push
  (`request-codex-review-on-push.yml`); the deterministic router (`fast-ai-code-review.yml`)
  routes every PR to Codex (the fast path is disabled here, so docs are reviewed too).
- **`Validate`** (`validate.yml`) is the CI gate; **fixed Codex threads auto-resolve**
  (`resolve-fixed-codex-review-threads.yml`); the **fail-closed foundation gate**
  (`auto-merge-foundation-prs.yml`) merges provably-ready PRs. Humans keep authority via `human-merge`.

> Status: **contract layer + GitHub renderer + `stagr` CLI, dogfooded.** The platform-neutral
> stage-graph schema, profiles, provider/model resolution, backends, cross-cutting policy, the GitHub
> renderer + generic backend, and the installable `stagr` CLI (`doctor`/`plan`/`apply`) are in place,
> alongside the toolkit's own live Claude+Codex automation. Next: multi-stage rendering, more platform
> renderers, and the front-door skill (see [ARCHITECTURE.md](docs/ARCHITECTURE.md) roadmap).

## License

stagr is **source-available** under the [Business Source License 1.1](LICENSE) — not a
traditional open-source license. In short: you may read, modify, redistribute, and use it free of
charge for internal and non-production work, and in production within a single organization on
repositories you control. Other production use — for example offering stagr to third parties as a
hosted or managed service, or embedding it in a product or service you provide to others — requires a
commercial license. Each released version converts to Apache 2.0 four years after its publication.

For commercial licensing, contact contact.exepex@gmail.com.
