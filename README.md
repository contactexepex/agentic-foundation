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

**Models are configurable and can be dynamic.** Set a default model per role, and optionally enable
**tiering**: a trivial textual/config change runs on a low-cost model, a large or complex change
escalates to a high-capability one. Tier selection is **deterministic** (reuses the review router's
change-size + path signal) — no extra model call.

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
