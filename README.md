# agentic-foundation

A reusable toolkit that drops an **AI implement → AI review → CI-gated pull request**
workflow into *any* GitHub repository. It is the generic engineering core extracted from the
`permission-api` project, with everything product-specific (Azure deploy, the runtime app, the
Permission-API domain) removed.

After a small, one-file configuration step, a target repository gets the same agentic pipeline
permission-api uses: one AI agent implements a change (docs or code), another AI agent reviews it,
CI enforces "green", and a pull request is opened for human review.

## What it is (and is not)

- **Is:** GitHub Actions workflows + a per-repo config contract + a deterministic installer + a
  Claude Code skill front door. Provider-, model-, and language-agnostic.
- **Is not:** a deployment system, a runtime, or anything tied to one language or one AI vendor.

## Flexible by design

**Roles are abstract; providers plug in.** You bind each role to a provider and a model, so every
combination works:

| Implementer | Reviewer | Config |
|---|---|---|
| Claude | Codex/OpenAI | `implementer.provider: claude`, `reviewer.provider: openai` |
| Codex/OpenAI | Claude | `implementer.provider: openai`, `reviewer.provider: claude` |
| Claude | Claude (different model) | both `claude`, different `model.default` |
| OpenAI | OpenAI (different model) | both `openai`, different `model.default` |

**Models are configurable, layered, and can be dynamic.** You don't have to specify a model at all:
each role resolves one through a precedence chain — **per-request override › per-repo model ›
org/account default › toolkit fallback** — so *providing a model overrides the default*, and omitting
it inherits. Optionally enable **tiering**: a trivial textual/config change runs on a low-cost model,
a large or complex change escalates to a high-capability one. Tier selection is **deterministic**
(reuses the review router's change-size + path signal) — no extra model call. See
[Model resolution](docs/CONFIGURATION.md#3a-model-resolution).

**Simple by default, advanced when you want it.** The only required config is `version` + `roles`
(each role's `provider`). A minimal file is a few lines; every other block is optional and falls back
to a sensible default. Add configuration only to take finer control.

**Secrets stay secret.** The toolkit never logs, prints, or exposes any credential (API key, token,
username, or password), never stores them, and keeps them out of `.agentic/config.yml` — see
[Secret handling](docs/CONFIGURATION.md#3b-secret-handling-non-negotiable).

**Everything adapts to your setup — nothing hardcoded.** All of the following are optional and
configurable, so an org, team, or individual can bend the toolkit to how they deploy, host, and
observe:

- **Config inheritance** (`extends`) — layer an org base → team base → repo; local values win.
- **Model aliases** — reference `fast`/`balanced`/`strong` (your names) and map IDs centrally.
- **Custom / self-hosted providers** — set a `base_url`, API version, deployment, and the *name* of
  the key secret (Azure OpenAI, proxies, on-prem gateways).
- **Cost & token budgets** — per-run and per-period caps; on exceed `block` / `downgrade` / `warn`.
- **Prompt-injection guardrails** — treat PR/issue/comment/diff content as data, not instructions.
- **Observability** — send run records to a file, CI artifact, webhook, or OTLP collector; endpoints
  come from a variable/secret *name*, never hardcoded; secrets always redacted.
- **`doctor` & `plan`** — validate config + secrets and dry-run the install before anything is applied.

**Language-agnostic.** A repo declares what "green" means (`install` / `lint` / `test` /
`typecheck`) via a preset (`python`, `maven`, `gradle`, `node`, `go`, `rust`, `dotnet`) or custom
commands. The workflows never assume a language.

## Modules

- **core** (always): implementer + reviewer + deterministic review routing + review-thread hygiene.
  Humans merge.
- **+auto_merge** (opt-in, off by default): the fail-closed foundation auto-merge gate.
- **+sonar** (opt-in): SonarQube/SonarCloud quality gate as a required check.

## Quickstart

1. In your target repo, add `.agentic/config.yml` (copy `templates/config/agentic.config.yml.tmpl`
   and edit it — or let the Claude skill draft it for you).
2. Create the required secrets/tokens for your chosen providers — see
   [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for exact names and whether each must be a
   **service account** or a **personal access token**.
3. Run the installer (or invoke the skill). It validates the config against
   `install/config.schema.json`, renders the module workflows into `.github/workflows/`, and opens a
   bootstrap PR.
4. Merge the bootstrap PR. The pipeline is live.

Full field-by-field reference, provider→secret mapping, and troubleshooting:
**[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**.

## Layout

```
templates/workflows/   tokenized GitHub Actions (rendered per config)
templates/contract/    AGENTS.md / CLAUDE.md skeletons (domain-free)
templates/config/      the .agentic/config.yml template
templates/presets/     per-ecosystem command presets
install/               config.schema.json, modules.yml, installer
skill/                 the Claude Code front-door skill
docs/                  CONFIGURATION.md and design notes
```

> Status: **M1 — contract layer.** Config schema, docs, and module map are in place; workflow
> tokenization and the installer/skill are in progress.
