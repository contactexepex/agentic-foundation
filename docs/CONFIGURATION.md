# Configuring agentic-foundation

This is the complete setup reference: what the toolkit needs, the exact secret/variable names, which
credentials must be a **service account** vs a **personal access token (PAT)**, and every field of
`.agentic/config.yml`.

---

## 1. Prerequisites

- A repository on a supported SCM platform (GitHub first; GitLab / Azure DevOps / Bitbucket / Gitea
  follow) that you can add pipelines and secrets to.
- Provider access for each provider your stages use (e.g. Claude, OpenAI, Gemini, or a self-hosted
  gateway).
- Optional: a SonarQube/SonarCloud project (only if you enable the `sonar` module).

The toolkit never creates credentials. The installer only **checks** that the required secrets exist
and fails loudly if one is missing.

---

## 2. Credentials — names, type, and scope

Set these as **repository (or environment) secrets** unless noted as a variable. Names are the
defaults the workflows read; keep them unless you also update the rendered workflows.

| Purpose | Name | Type | Required when | Scope / notes |
|---|---|---|---|---|
| Claude model access | `ANTHROPIC_API_KEY` | **Service account** (dedicated API key) | any role uses `provider: claude` | Never a personal key. Rotate independently. |
| OpenAI/Codex model access | `OPENAI_API_KEY` | **Service account** (dedicated API key) | any role uses `provider: openai` | Never a personal key. |
| Codex comment-trigger / PR publication | `CODEX_REMEDIATION_TOKEN` | **Fine-grained PAT (real user)** | reviewer or dispatch uses Codex's `@codex` comment flow | Least scope: **Contents: R/W** + **Pull requests: R/W**. **No** admin/merge. Must be a real, attributable user — bot/App tokens do not reliably trigger `@codex`. |
| SonarQube/SonarCloud token | `SONAR_TOKEN` | **Service account** | `modules.sonar: true` | Read/analysis scope for the project. |
| Sonar host (SonarQube only) | `SONAR_HOST_URL` | Variable | `modules.sonar: true` on self-hosted | Omit for SonarCloud. |
| GitHub API (statuses, PR reads) | `GITHUB_TOKEN` | Provided by Actions | always | No action needed; least-privilege per-workflow permissions are set in each workflow. |

**Why the split (PAT vs service account):**
- **Model API keys** (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) are machine credentials for paid model
  usage — use dedicated **service-account** keys so cost and access are isolated from any person and
  can be rotated without touching a human account.
- **`CODEX_REMEDIATION_TOKEN`** must be a **real-user PAT** because Codex acts on `@codex` commands
  only from an attributable user, and PR publication needs an attributable repository member. Grant
  it the minimum (Contents + Pull requests, R/W) — it needs no permission to merge or administer.

> Secret names are configurable. The names above are defaults; override them per provider with
> `providers.<provider>.api_key_secret` and per platform with `platform.auth.token_secret`. The
> installer's `doctor` command tells you exactly which secrets your chosen **stages** and providers
> require, checking each **by name** (never reading the value).

---

## 3. `.agentic/config.yml` — field reference

Copy `templates/config/agentic.config.yml.tmpl` to `.agentic/config.yml`. It is validated against
`install/config.schema.json`.

**Simple by default, advanced when you want it.** A runnable config needs a `version`, a `profile`
(default `standard`, which expands to a stage graph), and a `platform` (defaults to GitHub). A stage
whose backend consumes a model (the built-in `generic`/`claude-code-action`) also needs a model
binding (`defaults.models.<provider>`, or a per-stage model); app backends (e.g. `codex`) supply
their own model, so an all-app-backed graph needs no `defaults.models`. Model resolution is
fail-loud (see below) — no hidden default. That is still a few lines; add `stages` and other blocks
only to take finer control. See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

```yaml
# Minimal config — profile expands to a stage graph; models resolve from defaults/org.
version: 2
profile: standard
platform: { type: github, default_branch: main }
defaults:
  provider: claude
  models:
    claude: { default: "<claude-default-model>" }
    openai: { default: "<openai-default-model>" }
```

### `extends` (optional — config inheritance)
| Field | Meaning |
|---|---|
| `extends` | A path/URI, or ordered list of them, to base configs merged **before** this file. Local values win. Layer an org base → team base → this repo. Maps deep-merge; scalars and arrays are replaced by the later (more specific) layer. |

### `profile`
| Field | Meaning |
|---|---|
| `profile` | Onboarding shortcut that expands to a default stage graph: `minimal` (implement + review), `standard` (implement + review + security), `full` (plan + implement + security + test + integration-test + review + docs), or `custom` (no auto stages). Default `standard`. Stages you list under `stages` are merged on top (same id overrides). |

### `platform`
| Field | Meaning |
|---|---|
| `type` | `github` \| `gitlab` \| `azure_devops` \| `bitbucket` \| `gitea` \| `other`. Selects the renderer. GitHub ships first. |
| `host` | Self-hosted / enterprise host (e.g. `github.example.com`, a self-managed GitLab, `dev.azure.com/org`). Blank = public host. |
| `default_branch` | Trunk branch change-requests target. |
| `same_repo_only` | `true` = ignore fork PR/MR heads. Keep `true` unless you accept fork contributions (widens the threat model). |
| `trusted_roles` | Normalized permission levels allowed to drive agentic changes (`owner`, `member`, `collaborator`, `contributor`); the renderer maps them to the platform's own roles. |
| `auth.token_secret` | **Name** of the secret holding the platform API token. Never the value. |
| `labels.human_merge` | A change-request with this label is **never** auto-merged (human keeps merge authority). |
| `labels.dispatch` | Optional label that dispatches a task from an issue. |

### `defaults` (optional — org/account fallbacks)
| Field | Meaning |
|---|---|
| `provider` | Default provider id for stages that omit one. |
| `models.<provider>.default` | Default model ID for that provider when a stage does not set its own. Keep it here or seed it from an org base via `extends`. |
| `models.<provider>.tiers.{trivial,standard,complex}` | Per-tier default model for that provider, used when `tiering.enabled: true`. `<provider>` is any provider id. |

### `models` (optional — provider-agnostic aliases)
| Field | Meaning |
|---|---|
| `models.aliases.<name>.<provider>` | Map an alias name (you choose it, e.g. `fast`/`balanced`/`strong`) to a concrete model ID per provider id. Reference the alias anywhere a model is expected; ID churn then touches one place. |

### `providers` (optional — connection / self-hosted)
| Field | Meaning |
|---|---|
| `providers.<provider>.base_url` | Custom endpoint (self-hosted, Azure OpenAI, proxy, on-prem gateway). Blank = provider default. |
| `providers.<provider>.api_version` | API version, where the endpoint needs one (e.g. Azure OpenAI). |
| `providers.<provider>.deployment` | Deployment name, where applicable (e.g. Azure). |
| `providers.<provider>.api_key_secret` | **Name** of the secret holding the API key. Lets you use your own secret naming. Never the key value. |
| `providers.<provider>.extra_headers_secret` | **Name** of a secret holding extra headers (e.g. a gateway token). |

### `skills` (optional — methodology registry)
A **skill** is the reusable methodology/content for a stage (checklist, rubric, output format),
provider-/backend-/language-agnostic. Built-ins ship under `templates/skills/<id>/` (starter set:
`code-review`, `security-review`). Register your own or override a shipped one by id; a stage picks one
via `stages[].skill`.

| Field | Meaning |
|---|---|
| `skills.<id>.source` | `builtin` (uses `templates/skills/<id>/`), `path`, or `uri`. Default `builtin`. |
| `skills.<id>.path` / `.uri` | Location of the skill content for `path`/`uri` sources. |
| `skills.<id>.version` | Optional version pin. |
| `skills.<id>.extends` | Base skill id to layer on top of (base first, this overrides) — e.g. a house style over `code-review`. |

**Skills vs. agents vs. stages:** a *skill* is the content; an *agent preset* (`templates/agents/<id>.yml`)
is a pre-wired stage (type + skill + backend + gate + triggers, with an **optional** model binding —
presets may omit it so the model resolves via `defaults`) you drop in via `stages[].from`; a *stage*
is that agent placed in the pipeline graph.

### `stages` (optional — the agent graph)
Omit to use the profile's stages. Anything you list is **merged onto** the profile (a stage with the
same `id` overrides). Each stage is one agent; mix providers, models, and backends freely.

| Field | Meaning |
|---|---|
| `id` | **Required.** Unique stage id (`^[a-z0-9][a-z0-9-_]*$`), e.g. `plan`, `implement`, `security`, `integration-test`. |
| `type` | **Required.** `plan` \| `implement` \| `security` \| `test` \| `integration-test` \| `review` \| `docs` \| `release` \| `custom`. Drives sensible defaults (review/security/test default to a blocking gate; plan/docs to advisory). |
| `from` | Agent-preset id (from `templates/agents/`, e.g. `code-review`, `security-review`) to base this stage on. Fields you set here override the preset. |
| `name` | Human-readable label. |
| `enabled` | `false` to keep a stage defined but off. Default `true`. |
| `provider` | Provider id for this stage. Omit to inherit `defaults.provider`. |
| `model` (+ `.default`, `.tiers.*`) | Optional model binding; inherits per the resolution chain. A value may be a literal ID or a `models.aliases` name. |
| `skill` | Skill id (from `skills` registry or a built-in) supplying this stage's methodology. Takes precedence over inline `instructions`. |
| `backend` | The executor (see below). Defaults to the generic runner. |
| `triggers` | Any of `issue_labeled`, `pr_opened`, `pr_updated`, `comment_command`, `push`, `schedule`, `manual`. |
| `gate` | `advisory` (comment only) or `blocking` (emits a required status check). Omit to use the type's default. |
| `tiering` | Per-stage override of global `tiering.enabled`. |
| `depends_on` | Ids of stages that must run first (defines the graph edges). |
| `budgets` | Per-stage cost/token ceilings (same shape as global `budgets`). |
| `instructions` | Inline prompt/policy for the stage, or a path to a prompt file. |

#### `stages[].backend`
| Field | Meaning |
|---|---|
| `name` | `generic` (built-in prompt-runner) \| `claude-code-action` \| `openhands` \| `pr-agent` \| `codex` \| `swe-agent` \| `custom`. |
| `uses` | Action ref or container image (for `custom`, or to pin/override an adapter). |
| `with` | Backend-specific inputs, passed through unchanged. |

See **Model resolution** below for the full precedence order.

### `tiering`
| Field | Meaning |
|---|---|
| `enabled` | Turn dynamic model selection on/off. |
| `classifier` | `deterministic` (v1). Tier comes from change size + paths — no extra model call. |
| `thresholds.trivial` | `max_files`, `max_lines`, `only_paths` — a change within these is `trivial`. |
| `thresholds.complex` | `min_files`, `min_lines` — a change at/above these is `complex`. Anything in between is `standard`. |

### `build` (optional)
| Field | Meaning |
|---|---|
| `preset` | `python \| maven \| gradle \| node \| go \| rust \| dotnet \| custom`. Pre-fills `commands` from `templates/presets/` (the presets directory is a planned M2 deliverable; until then, set `commands` directly). |
| `commands.{install,lint,test,typecheck}` | What "green" means for this repo. The workflows run exactly these — **any language**. Override any preset value. |

Omit `build` entirely (or leave `commands` empty) for a repo with no build gate, e.g. docs-only.

### `routing.fast_path`
| Field | Meaning |
|---|---|
| `globs` | Paths eligible for fast-path approval without a model review. |
| `max_files` / `max_lines` | Size ceiling for the fast path. |
| `exclude` | Paths never fast-pathed (e.g. `AGENTS.md`, `.agentic/**`). |

### `modules`
| Field | Meaning |
|---|---|
| `auto_merge` | `true` installs the fail-closed foundation auto-merge gate. Default `false`. |
| `sonar` | `true` wires SonarQube/SonarCloud as a required check. Default `false`. |

### `budgets` (optional — cost / token caps)
| Field | Meaning |
|---|---|
| `enabled` | Turn budget enforcement on. Default `false`. |
| `currency` | Currency for `max_usd` limits. Default `USD`. |
| `per_run.{max_usd,max_tokens}` | Ceiling for a single run. |
| `per_period.{window,max_usd,max_tokens}` | Rolling ceiling over `daily`/`weekly`/`monthly`. |
| `on_exceed` | `block` (stop the run), `downgrade` (drop to a cheaper tier), or `warn`. Default `block`. |

### `guardrails` (optional — prompt-injection controls)
| Field | Meaning |
|---|---|
| `untrusted_inputs` | Which inputs are treated as **data, not instructions** (`pr_body`, `issue_body`, `comments`, `diff`, `code_comments`, `filenames`). |
| `ignore_inline_directives` | Ignore "instructions" embedded in untrusted content. Default `true`. |
| `allowed_tools` | Optional allowlist of tools the agent may use. |
| `max_context_files` | Cap on files pulled into context. |
| `redact_secrets_in_context` | Strip secret-shaped strings from model context. Default `true`. |

### `observability` (optional — audit trail; adapt to your stack)
| Field | Meaning |
|---|---|
| `enabled` | Emit run records. Default `true`. |
| `format` | `json` or `text`. Default `json`. |
| `redact_secrets` | Secrets are **always** redacted from output; this flag cannot expose them. |
| `sinks[].type` | `none`, `artifact` (CI artifact), `file`, `webhook`, or `otlp`. Use several. |
| `sinks[].path` | Destination for `file`. |
| `sinks[].endpoint_var` | **Name** of a variable holding the URL for `webhook`/`otlp` — never hardcoded. |
| `sinks[].headers_secret` | **Name** of a secret holding auth headers/token. |
| `sinks[].min_level` | `debug`/`info`/`warn`/`error`. Default `info`. |

---

## 3a. Model resolution

Each **stage's** model is resolved per run, **most specific wins**. For a given stage and change tier
the toolkit walks this chain and uses the first model it finds:

| # | Layer | Where it comes from |
|---|---|---|
| 1 | **Per-request override** | A model supplied at dispatch time (a pipeline input or a dispatch-comment command). Wins over everything. |
| 2 | **Stage model** | `stages[].model.tiers.<tier>`, then `stages[].model.default`. |
| 3 | **Org/account default** | `defaults.models.<provider>.tiers.<tier>`, then `defaults.models.<provider>.default` (provider = the stage's provider, or `defaults.provider`). |

For a stage whose backend consumes a contract model (the built-in `generic`/`claude-code-action`),
if none of layers 1–3 yields a model, resolution **fails loudly** (see below) — there is no hidden
built-in default, so the toolkit never silently picks a model version. App backends (e.g. `codex`)
supply their own model, so this rule does not apply to them: an all-app-backed graph is valid with
no `defaults.models`.

Key points:

- **Provide a model → it overrides the default.** Set one at any layer to override every layer below
  it; leave it unset to inherit. You can override just one tier (e.g. `complex`) and let the rest
  inherit.
- **Tier** (`trivial` / `standard` / `complex`) comes from the deterministic classifier (change size
  + paths) only when `tiering.enabled: true`; otherwise `default` is used.
- **Aliases resolve last.** If the resolved value matches a `models.aliases` name, it maps to that
  alias's model ID for the stage's provider — so you can pin `strong` once and swap the ID centrally.
- **Fail loudly, never guess.** If no model resolves for a stage/tier, the installer/run stops with a
  clear error naming the stage and which key to set — it never silently picks a model version.

**Example** — org sets the defaults; one review stage pins only its complex tier and uses a different
provider than the implementer (any permutation is valid):

```yaml
defaults:
  provider: claude
  models:
    claude: { default: "<claude-default>" }
    openai: { default: "<openai-default>", tiers: { complex: "<openai-complex>" } }
stages:
  - id: implement
    type: implement
    provider: claude                                          # -> <claude-default>
  - id: review
    type: review
    provider: openai
    model: { tiers: { complex: "<openai-strong>" } }          # complex -> <openai-strong>; else <openai-default>
```

---

## 3b. Secret handling (non-negotiable)

The toolkit treats every credential as write-only and invisible:

- **Never logged, never printed, never echoed.** No secret — API key, token, username, or password —
  is written to workflow logs, step output, PR/issue comments, review text, error messages, or any
  artifact. Commands that could surface a secret are masked or avoided.
- **Passed only to the step that needs it,** via GitHub Actions secrets / `env`, scoped to the
  minimal job — never interpolated into a shell string that gets logged, and never persisted to disk.
- **The toolkit never creates or stores credentials.** The installer only checks a required secret
  *exists* (by name) and fails loudly if one is missing — it does not read or emit the value.
- **No secret in config.** `.agentic/config.yml` holds only non-sensitive settings; credentials live
  in repo/environment secrets (section 2). Do not put tokens in the config file.

If you ever see a secret value in a log or comment, treat it as compromised and rotate it.

---

## 3c. Commands: `doctor` and `plan` (dry-run)

Two read-only commands help you verify configuration before anything is applied. (Enforced by the
installer/engine; defined here as the contract.)

**`doctor` — validate.** Fails loudly and fixes nothing. It:
- validates `.agentic/config.yml` (after `extends` merge) against the schema;
- confirms every required secret **exists by name** for the providers/modules in use (never reads
  the value);
- resolves and prints the **model matrix** (each stage × tier → model, showing which layer won and
  any alias expansion);
- checks `providers`, `budgets`, and `observability` are well-formed and that referenced
  variable/secret **names** are present.

**`plan` — dry-run.** Prints what the installer *would* render — the enabled modules, workflow files,
resolved models, gates, and budgets — **without writing files or opening a PR.** Output is
secret-free.

---

## 4. Presets

A preset only pre-fills `build.commands`. Example shapes (set your real commands):

| Preset | install | lint | test |
|---|---|---|---|
| `python` | `pip install -r requirements.txt` | `ruff check .` | `python -m pytest` |
| `maven` | `mvn -q -N install` | `mvn -q spotless:check` | `mvn -q verify` |
| `gradle` | `./gradlew dependencies` | `./gradlew check -x test` | `./gradlew test` |
| `node` | `npm ci` | `npm run lint` | `npm test` |
| `go` | `go mod download` | `golangci-lint run` | `go test ./...` |
| `rust` | `cargo fetch` | `cargo clippy -- -D warnings` | `cargo test` |
| `dotnet` | `dotnet restore` | `dotnet format --verify-no-changes` | `dotnet test` |

---

## 5. Setup steps

> **Status:** the renderer (M2), the `doctor`/`plan`/`apply` CLI (M3), and the front-door skill (M4)
> are **not shipped on `main` yet** (see the roadmap). Steps 3–4 below describe the intended automated
> experience; today, follow the manual path noted in each.

1. Add `.agentic/config.yml` (edit the template — the drafting skill is M4). Start with a `profile`,
   a `platform`, and a model binding for any model-consuming stage; add `stages` only for finer control.
2. Create the secrets your stages/providers and platform require (section 2). (`doctor` will list the
   exact set by name once M3 ships.)
3. **Planned (M2/M3):** run `agentic apply` — it validates the config, renders the enabled stages for
   your `platform`, and installs the pipeline. **Today (manual):** hand-adapt the automation you need;
   the toolkit's own `.github/workflows/` validate *this* repo's contract and are references, not
   drop-in files.
4. **Planned:** merge the bootstrap PR/MR. **Today:** commit the workflows you adapted.

---

## 6. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Reviewer never runs on Codex | `CODEX_REMEDIATION_TOKEN` missing or not a real-user PAT. |
| Endpoints/agents fail auth | Model API key secret missing or wrong name. |
| Fast path never triggers | Change exceeds `routing.fast_path` size, or path is in `exclude`. |
| Wrong model tier chosen | Review `tiering.thresholds`; deterministic tiering keys off files/lines/paths only. |
| Auto-merge never fires | `modules.auto_merge` is `false`, or a gate signal (CI/review/threads) is not green. |
