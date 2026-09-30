# agentic-foundation

A reusable toolkit that drops a configurable **graph of SDLC/STLC agent stages** — implement,
review, security, build, test, and more — into *any* repository, on *any* SCM platform, in *any* language,
with *any* provider/model per stage. It is the generic engineering core extracted from the
`permission-api` project, with everything product-specific (Azure deploy, the runtime app, the
Permission-API domain) removed.

After a small, one-file configuration step, a target repository gets an agentic pipeline: each stage
is an AI agent bound to the provider, model, and backend you choose; stages gate on CI; and a pull/
merge request is opened for human review.

## What it is (and is not)

- **Is:** a platform-neutral **config contract** + per-platform renderers + pluggable agent
  backends + a CLI (`help`, `plan` and `apply` today; `init` and `doctor` are planned) + a
  Claude Code skill front door (planned). Provider-, model-, platform-, and language-agnostic.
- **Is not:** an agent (it *composes* mature OSS agents), a deployment system, a runtime, or anything
  tied to one language, one AI vendor, or one Git host.

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the design and
**[docs/LANDSCAPE.md](docs/LANDSCAPE.md)** for how it differs from existing tools.

## Flexible by design

**Stages are agents; anything plugs in.** A pipeline is an ordered, extensible graph of stages. Each
stage binds a **role/type** (implement, review, security, build, test, deploy, custom) to a
**provider + model**; the coding tool is derived from the provider — `anthropic` runs Claude Code,
`openai` runs Codex:

| Stage | Provider | Model | Tool (derived) |
|---|---|---|---|
| implement | anthropic | set in `defaults.models.anthropic` or the stage | Claude Code |
| review | openai | app-supplied | Codex |
| security | openai | app-supplied | Codex |

Mix Anthropic and OpenAI per stage, or vary the Anthropic model across stages. Today the toolkit
has backend renderers for **Anthropic (Claude Code)** and **OpenAI (Codex)**; more providers/tools
are roadmap and slot in through the same provider→tool map without forking the contract. The GitHub
renderer can render only backends that are started by a pull-request comment (the Codex review and
security stages); config validation rejects an `implement` stage on GitHub until the implementer can
be rendered there.

**Models are configurable and layered.** You need not specify a model at all: each stage resolves
one through a precedence chain — **stage model › `defaults.models.<provider>.default`** (then it
fails loudly if unresolved — no hidden fallback) — so *providing a model overrides the default*, and
omitting it inherits.

**Any platform.** `platform.type` (github | gitlab | azure_devops | bitbucket | gitea) selects a
renderer that maps the same contract to that system (PR↔MR, roles, required checks). GitHub is the
only renderer today; others follow.

**Compose, don't reinvent.** New tools plug in through one seam: a stage's optional `backend` override
wraps a mature OSS agent (OpenHands, PR-Agent, SWE-agent) or a custom adapter — roadmap today, added
without touching the rest. Normally you omit it and let the provider choose the tool.

**Skills.** Reusable **skills** (methodology: checklist, rubric, output format —
provider/backend/language-agnostic) are the content; a stage points at one with `skill:`. Ships with
`code-review` and `security-review` skills. See
[skills](docs/ARCHITECTURE.md#3a-skills--content-vs-wiring).

**Simple by default, advanced when you want it.** A runnable config is a `version`, a `profile`
(`minimal`/`standard`/`custom`; `minimal` and `standard` expand to a default stage graph), a
`platform`, and `platform.publisher.app_id` (the ID of your Stagr GitHub App, which `stagr plan` and
`stagr apply` need). An `anthropic` stage (Claude Code) also needs a model binding
(`defaults.models.anthropic`, or a per-stage model); an `openai` stage (Codex) supplies its own.
Model resolution is fail-loud — no hidden default. Still a few lines; define `stages` only for finer
control.

**Secrets stay secret.** The toolkit never logs, prints, or exposes any credential (API key, token,
username, or password), never stores them, and keeps them out of `.agentic/config.yml` — see
[Secret handling](docs/CONFIGURATION.md#3b-secret-handling-non-negotiable).

**Nothing is hardcoded.** The config names everything that varies, so an org, team, or individual
can bend the toolkit to how they deploy and host:

- **Profiles** (`minimal`/`standard`/`custom`) — expand to a default stage graph; override any part.
- **Providers and secrets** — any provider id, and the *name* of the secret that holds its key.
- **Fast-path routing** — send docs-only or other trivial changes to a lighter set of stages, or
  turn it off so every PR gets every stage.

**Language-agnostic.** Stages never assume a language. How a repo declares what "green" means
(build and test commands) is designed in
[design-docs/09-check-stages.md](design-docs/09-check-stages.md); the config does not read it yet.

## Quickstart

The install, `stagr help`, `stagr plan` and `stagr apply` work today; `init` and `doctor` are still
being rebuilt (see [docs/CLI.md](docs/CLI.md)).

1. **Install the CLI** (needs only Python 3.10+; see [docs/CLI.md](docs/CLI.md) for options). `stagr`
   is not on PyPI yet, so install it from the repository's source archive — pip/pipx download and
   build it with no `git` required:
   ```bash
   pipx install "https://github.com/contactexepex/agentic-foundation/archive/refs/heads/main.tar.gz"
   # once published this becomes: pipx install stagr
   ```
   For a reproducible, auditable install, pin the URL to a commit SHA (or a release tag) instead of
   `main` — see [docs/CLI.md](docs/CLI.md).
2. Run `stagr help` to see the available commands.
3. Write `.agentic/config.yml` by hand in your target repo. The full field reference, provider→secret
   mapping, and troubleshooting are in **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**.
4. Run `stagr plan` in the repo root to validate the config and list the files it produces (nothing is
   written), then `stagr apply` to write those same files under `.github/workflows/`.

**Planned commands** (not available yet): `stagr init` creates a starting config and will ask for the
GitHub App ID; `stagr doctor` checks the config and lists the secret names to create (issue #203).

> **What exists today:** the neutral core validates a config, expands the profile, resolves
> providers, backends, and models, and builds the stage graph. The GitHub renderer turns that graph
> into artifacts — a workflow per stage, a routing workflow, and a governance (merge-gate) workflow —
> and never writes files itself. A stage can be rendered on GitHub only if its backend is started by
> a pull-request comment, which today means the Codex `review` and `security` stages. Other stage
> types are declared and validated but cannot be rendered yet ([docs/CHARTER.md](docs/CHARTER.md) §7).

## Layout

```
stagr/                                 the installable package
stagr/cli/                             the `stagr` command (`help`, `plan`, `apply` today)
stagr/core/                            the neutral core: config validation, normalization, stage graph,
                                       backend renderers (renderers/)
stagr/platforms/github/                the GitHub renderer
stagr/config.schema.json               the config contract
stagr/templates/skills/<id>/           reusable skill methodologies (code-review, security-review)
pyproject.toml                         packaging for the `stagr` command
docs/                                  ARCHITECTURE.md, CONFIGURATION.md, CLI.md, CHARTER.md, LANDSCAPE.md
design-docs/                           the design of the neutral core and renderers
.github/workflows/                     this repo's own hand-written automation
.github/scripts/                       validate_config.py + tests
.agentic/config.yml                    this repo's own agentic contract (dogfood)

# Planned (see ARCHITECTURE.md roadmap):
stagr/templates/presets/               per-ecosystem command presets
skill/                                 the Claude Code front-door skill (M4)
```

## Dogfooding

This repository runs the pattern on itself. `.agentic/config.yml` is its declarative source of truth
(a Codex review stage and a Codex security stage), and `.github/workflows/` are the hand-written
**reference implementation** the GitHub renderer (`stagr/platforms/github/`) is modelled on:

- **Claude implements** (`claude-code-implementor.yml`, manual dispatch) and **Codex implements**
  (`authorized-engineering-task.yml`, on the `codex-engineering` issue label) via an
  untrusted-implement → validate → trusted-publish (remediation) flow.
- **Codex reviews** — code and security — is re-requested on every push
  (`request-codex-review-on-push.yml`); the deterministic router (`fast-ai-code-review.yml`)
  routes every PR to Codex (the fast path is disabled here, so docs are reviewed too).
- **`Validate`** (`validate.yml`) is the CI gate; **fixed Codex threads auto-resolve**
  (`resolve-fixed-codex-review-threads.yml`); the **fail-closed foundation gate**
  (`auto-merge-foundation-prs.yml`) merges provably-ready PRs. Humans keep authority via
  `human-merge`. All of these workflows are hand-written for this repository; none is a Stagr feature.

> Status: **neutral core + GitHub renderer, dogfooded.** The platform-neutral stage-graph schema,
> profiles, provider/backend/model resolution, and the GitHub renderer (per-stage, routing, and
> governance workflows) and the `stagr plan` / `stagr apply` commands are in place, alongside the
> toolkit's own live Claude+Codex automation. Next: the `init`/`doctor` commands, more stage types, more platform renderers, and the
> front-door skill (see [ARCHITECTURE.md](docs/ARCHITECTURE.md) roadmap).

## License

stagr is **source-available** under the [Business Source License 1.1](LICENSE) — not a
traditional open-source license. In short: you may read, modify, redistribute, and use it free of
charge for internal and non-production work, and in production within a single organization on
repositories you control. Other production use — for example offering stagr to third parties as a
hosted or managed service, or embedding it in a product or service you provide to others — requires a
commercial license. Each released version converts to Apache 2.0 four years after its publication.

For commercial licensing, contact contact.exepex@gmail.com.
