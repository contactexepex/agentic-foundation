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
- Optional: an external code-quality/security tool (SonarCloud, SonarQube, Checkmarx, …) if you want
  its check required before auto-merge. Install the tool's **GitHub App** so it publishes its own
  check-run on the PR, then list that check's `name` and the App's numeric `app_id` in
  `merge.required_status_checks`; stagr never runs the tool. (A scan you instead run inside your build is
  covered by the `Validate` check — do **not** list it, since the gate requires a check-run from that
  specific App id, not a `github-actions` run.)

The toolkit never creates credentials. The installer only **checks** that the required secrets exist
and fails loudly if one is missing.

---

## 2. Credentials — names, type, and scope

Set these as **repository (or environment) secrets** unless noted as a variable. Names are the
defaults the workflows read; keep them unless you also update the rendered workflows.

| Purpose | Name | Type | Required when | Scope / notes |
|---|---|---|---|---|
| Claude model access | `ANTHROPIC_API_KEY` | **Service account** (dedicated API key) | any role uses `provider: anthropic` | Never a personal key. Rotate independently. |
| OpenAI model access (roadmap) | `OPENAI_API_KEY` | **Service account** (dedicated API key) | **Not required today** — `openai` runs Codex, which is app-backed and supplies its own model. Reserved for a future model-consuming OpenAI backend. | Never a personal key. |
| Codex comment-trigger / PR publication | `REMEDIATION_TOKEN` | **Fine-grained PAT (real user)** | reviewer or dispatch uses Codex's `@codex` comment flow | Least scope: **Contents: R/W** + **Pull requests: R/W**. **No** admin/merge. Must be a real, attributable user — bot/App tokens do not reliably trigger `@codex`. |
| GitHub API (statuses, PR reads) | `GITHUB_TOKEN` | Provided by Actions | always | No action needed; least-privilege per-workflow permissions are set in each workflow. |

> **External quality/security tools (SonarCloud, Checkmarx, …) are configured outside stagr.** stagr
> does not run them and needs no `SONAR_TOKEN`/etc. of its own. Install the tool's **GitHub App** (org
> level) so it publishes its own **check-run** on the PR, and list that check's `name` + `app_id` in
> `merge.required_status_checks` so the auto-merge gate requires it. The gate matches by exact name **and**
> that App id — so a scan run as a step in your `build.commands` is **not** listed here; it is covered by
> the `Validate` check
> instead. Any credentials the tool needs live in that tool's own setup, not in stagr's contract.

**Why the split (PAT vs service account):**
- **Model API keys** (today `ANTHROPIC_API_KEY`; `OPENAI_API_KEY` is roadmap — Codex supplies its own
  model) are machine credentials for paid model usage — use dedicated **service-account** keys so cost
  and access are isolated from any person and can be rotated without touching a human account.
- **`REMEDIATION_TOKEN`** must be a **real-user PAT** because Codex acts on `@codex` commands
  only from an attributable user, and PR publication needs an attributable repository member. Grant
  it the minimum (Contents + Pull requests, R/W) — it needs no permission to merge or administer.

> Secret names are configurable. The names above are defaults; override them per provider with
> `providers.<provider>.api_key_secret` and per platform with `platform.auth.token_secret`. The
> installer's `doctor` command tells you exactly which secrets your chosen **stages** and providers
> require, checking each **by name** (never reading the value).

---

## 3. `.agentic/config.yml` — field reference

The easiest way to create `.agentic/config.yml` is **`stagr init`**, which writes a commented starter
config for you — no hand-editing from a reference required:

- `stagr init` — a short guided wizard (scope, platform, model/secrets, build checks, governance),
  each prompt showing its options and default; press Enter to accept.
- `stagr init --profile <minimal|standard|full|custom>` — generate the file non-interactively (for
  CI or when you already know what you want). Add `--print` to preview, `--force` to overwrite.

Every generated file validates and renders. See [CLI.md](CLI.md) for the full `init` reference and the
**init → doctor → plan → apply** flow.

Prefer to write it by hand? The annotated template ships inside the installed package; download it
rather than copying from the install:
[`agentic.config.yml.tmpl`](https://raw.githubusercontent.com/contactexepex/agentic-foundation/main/stagr/templates/config/agentic.config.yml.tmpl)
(e.g. `curl -o .agentic/config.yml <that URL>`), or start from the minimal example in section 5. Either
way the file is validated against
[`stagr/config.schema.json`](https://raw.githubusercontent.com/contactexepex/agentic-foundation/main/stagr/config.schema.json).

**Simple by default, advanced when you want it.** A runnable config needs a `version`, a `profile`
(default `standard`, which expands to a stage graph), and a `platform` (defaults to GitHub). An
`anthropic` stage (Claude Code) also needs a model binding (`defaults.models.anthropic`, or a
per-stage model); an `openai` stage (Codex) supplies its own model, so an all-Codex graph needs no
`defaults.models`. Model resolution is fail-loud (see below) — no hidden default. That is still a
few lines; add `stages` and other blocks only to take finer control. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the design.

```yaml
# Minimal config — profile expands to a stage graph; models resolve from defaults/org.
version: 2
profile: standard
platform: { type: github, default_branch: main }
defaults:
  provider: anthropic
  models:
    anthropic: { default: "<anthropic-default-model>" }
    openai: { default: "<openai-default-model>" }
```

### `extends` (optional — config inheritance)
| Field | Meaning |
|---|---|
| `extends` | A path, or ordered list of paths, to base configs merged **before** this file. Local values win. Layer an org base → team base → this repo. Maps deep-merge; scalars and arrays are replaced by the later (more specific) layer. **Every base must live inside the repository checkout** (the project root): stagr operates on the current repo and treats config content as untrusted, so a base resolving outside the checkout (an absolute path, a `../` escape, or a symlink out) is **rejected at load time**. To share an org base, **vendor it into the repo** — commit it, add it as a submodule, or fetch it at checkout so it lands inside the tree — rather than pointing at a path outside the repo. (`uri:` remote bases are not fetched offline; vendor them locally.) |

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
provider-/backend-/language-agnostic. Built-ins ship under `stagr/templates/skills/<id>/` (starter set:
`code-review`, `security-review`). Register your own or override a shipped one by id; a stage picks one
via `stages[].skill`.

| Field | Meaning |
|---|---|
| `skills.<id>.source` | `builtin` (uses `stagr/templates/skills/<id>/`), `path`, or `uri`. Default `builtin`. |
| `skills.<id>.path` / `.uri` | Location of the skill content for `path`/`uri` sources. |
| `skills.<id>.version` | Optional version pin. |
| `skills.<id>.extends` | Base skill id to layer on top of (base first, this overrides) — e.g. a house style over `code-review`. |

**Skills vs. agents vs. stages:** a *skill* is the content; an *agent preset* (`stagr/templates/agents/<id>.yml`)
is a pre-wired stage (type + skill + provider + gate + triggers, with an **optional** model binding —
presets may omit it so the model resolves via `defaults`) you drop in via `stages[].from`; a *stage*
is that agent placed in the pipeline graph.

### `stages` (optional — the agent graph)
Omit to use the profile's stages. Anything you list is **merged onto** the profile (a stage with the
same `id` overrides). Each stage is one agent. Today an **implement** stage must be `anthropic`
(Claude Code) and a **review/security** stage must be `openai` (Codex) — mix these per stage. Other
pairings are roadmap: an `openai` implement stage fails loud at render, and an `anthropic`
review/security stage renders no lane yet.

| Field | Meaning |
|---|---|
| `id` | **Required.** Unique stage id (`^[a-z0-9][a-z0-9-_]*$`), e.g. `plan`, `implement`, `security`, `integration-test`. |
| `type` | **Required.** `plan` \| `implement` \| `security` \| `test` \| `integration-test` \| `review` \| `docs` \| `release` \| `custom`. Drives sensible defaults (review/security/test default to a blocking gate; plan/docs to advisory). |
| `from` | Agent-preset id (from `stagr/templates/agents/`, e.g. `code-review`, `security-review`) to base this stage on. Fields you set here override the preset. |
| `name` | Human-readable label. |
| `enabled` | `false` to keep a stage defined but off. Default `true`. |
| `provider` | **The primary knob.** `anthropic` runs Claude Code (implement stages); `openai` runs Codex (review/security stages). The executor is derived from this, so a stage normally sets only `provider` + `model`. Omit to inherit `defaults.provider`. |
| `model` (+ `.default`, `.tiers.*`) | Optional model binding; inherits per the resolution chain. A value may be a literal ID or a `models.aliases` name. |
| `skill` | Skill id (from `skills` registry or a built-in) supplying this stage's methodology. Takes precedence over inline `instructions`. |
| `backend` | **Optional override** (see below). Normally omit it — the executor is derived from `provider`. Set it only to pin a specific tool or point at a custom adapter. |
| `triggers` | Any of `issue_labeled`, `pr_opened`, `pr_updated`, `comment_command`, `push`, `schedule`, `manual`. |
| `gate` | `advisory` (comment only) or `blocking` (emits a required status check). Omit to use the type's default. |
| `tiering` | Per-stage override of global `tiering.enabled`. |
| `depends_on` | Ids of stages that must run first (defines the graph edges). |
| `budgets` | Per-stage cost/token ceilings (same shape as global `budgets`). |
| `instructions` | Inline prompt/policy for the stage, or a path to a prompt file. |

#### `stages[].backend` (optional override)
Normally you do **not** set `backend` — the executor is **derived from `provider`** (`anthropic` → Claude Code, `openai` → Codex). Set it only to pin a specific tool or point at a custom adapter.

| Field | Meaning |
|---|---|
| `name` | The executor to pin. **Rendered today:** `claude-code-action` (the Anthropic implementer) and `codex` (the OpenAI review/security lane). **Roadmap** (accepted so configs stay forward-compatible, not rendered yet): `generic`, `openhands`, `pr-agent`, `swe-agent`, `custom`. |
| `uses` | Action ref or container image (for `custom`, or to pin/override an adapter). |
| `with` | Backend-specific inputs, passed through unchanged. |

> **Supported today:** set `provider` to `anthropic` (runs **Claude Code** — implement stages) or `openai` (runs **Codex** — review/security stages) and the tool follows. Other provider/backend names are accepted for forward-compatibility but are **roadmap** (not rendered yet); adding one later is a small change (a new entry in the renderer's provider→tool map and lane registry). Model binding applies only where a model is consumed: an `anthropic` stage takes a free-form Anthropic model ID via `stages[].model`, `defaults.models.anthropic`, or `models.aliases`; an `openai`/Codex stage is app-backed and supplies its own model, so a binding there is ignored. An **implement** stage must be `anthropic` — an `openai` implement stage is roadmap (a Codex implementer is not rendered yet) and fails loud at render.

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
| `preset` | `python \| maven \| gradle \| node \| go \| rust \| dotnet \| custom`. Pre-fills `build.commands` with that toolchain's install/lint/test (see [§4 Presets](#4-presets) for the exact commands); `custom` pre-fills nothing. Any command you set under `commands` overrides the preset per key. `stagr init` **autodetects** this from your repo's build markers and proposes it as the default. Detection is conservative — it picks a preset only when the repo has the marker that preset's commands need (`requirements.txt` → `python`, `pom.xml` → `maven`, `gradlew` → `gradle`, `package-lock.json`/`npm-shrinkwrap.json` → `node`, `go.mod` → `go`, `Cargo.toml` → `rust`, `*.csproj`/`*.sln` → `dotnet`), and otherwise proposes `custom` rather than a preset whose commands would fail. Because a preset activates real CI commands (injected at render time, not written into the config), preview them with `python -m stagr.render --print` and override any that don't fit by setting `commands`. |
| `commands.{install,lint,test,typecheck}` | What "green" means for this repo. The workflows run exactly these — **any language**. Override any preset value. |

Omit `build` entirely (or leave `commands` empty) for a repo with no build gate, e.g. docs-only.

### `routing.fast_path`
| Field | Meaning |
|---|---|
| `enabled` | `false` disables the fast path so every PR (docs included) is routed to the reviewer. Default `true`. |
| `globs` | Paths eligible for fast-path approval without a model review. |
| `max_files` / `max_lines` | Size ceiling for the fast path. |
| `exclude` | Paths never fast-pathed (e.g. `AGENTS.md`, `.agentic/**`). |

Set `enabled: false` when every change must go through review — e.g. a shared toolkit whose
documentation other people depend on. This repository does exactly that.

### `modules`
| Field | Meaning |
|---|---|
| `auto_merge` | `true` renders the fail-closed auto-merge gate (`auto-merge.yml`). Default `false` — the unconfigured default is human-merge. |
| `sonar` | Reserved boolean; **not rendered** (a code-quality tool is wired tool-agnostically via `merge.required_status_checks` instead — see below). Default `false`. |

When `auto_merge` is on, a PR auto-merges once it is **provably ready**. A per-PR `human-merge` label
(`labels.human_merge`) is the hard stop that pauses that one PR for a human, and a PR that changes the
**control plane** (`merge.protected_paths` — CI/gate workflows, toolkit config) is likewise left for a
human. The gate requires green CI (the `Validate` check — authenticated as the trusted `validate.yml`
run for the exact head — plus every check-run/status), a head-bound Codex **code** review and — when a
Codex security stage is configured — a head-bound Codex **security** review, zero unresolved review
threads, no reviewer requesting changes, a trusted same-repo non-draft head on the default branch, and
every `merge.required_status_checks` check green. It is fail-closed: any missing/unknown signal or API
error skips the merge, retried on the next event or the scheduled sweep. It never checks out or runs PR
content (it runs on `pull_request_target` with API reads only).

**Merge model and the residual race.** The gate evaluates every predicate, then **re-evaluates them a
second time against freshly-fetched state immediately before merging**, and pins the merge to the
evaluated head SHA — so a PR whose head moved, whose checks went red, or that gained a label/change-request
between the two reads is not merged. GitHub's API is not transactional, so this **narrows but cannot fully
eliminate** the last-read→merge window; it is honest best-effort, not an atomic guarantee. Making these
checks **required in branch protection** is the only server-atomic closure, and also the only way to
authenticate the *content* of `validate.yml` against substitution — the control-plane guard is what covers
that within the gate's own authority. See `AGENTS.md`.

### `merge` (optional — auto-merge-gate policy)
| Field | Meaning |
|---|---|
| `required_status_checks` | External check-runs that must be present and green on the head before auto-merge, as `{name, app_id}` entries — the exact check-run **name** and the **immutable numeric GitHub App id** that must produce it, e.g. `[{name: "SonarCloud Code Analysis", app_id: 12345}]`. Identity is positive (name **and** `app.id`): a same-name check from any other App does not count. Its **latest** attempt (by check-run id) must be a clean success — a later cancelled/failed rerun is not superseded by an older green. Default `[]` (none). |
| `protected_paths` | Globs whose modification forces human review: a PR changing any matching file is never auto-merged (same effect as the `human-merge` label). These are the security-sensitive control plane — CI/gate workflow definitions and toolkit config/contract — whose changes need human judgement and whose *content* the gate cannot authenticate. Default `[".github/workflows/**", ".agentic/**"]`; set to `[]` only if you accept auto-merging changes to your own gate. |
| `method` | The merge method the gate uses: `squash` (default), `merge`, or `rebase`. The target repository must have that method enabled, or GitHub rejects every merge. |

> The auto-merge gate requires a Codex review only for a **blocking** review/security stage (an
> `advisory` stage stays comment-only). Because a blocking Codex review must cover pushed heads, enabling
> `auto_merge` with a blocking Codex `review` stage requires that stage to include the `pr_updated`
> trigger **and** `routing.fast_path.enabled: false` — otherwise a fast-path-approved or open-only head
> would have no head-bound review and could never merge. `stagr doctor`/`plan` fail loud on these
> incompatible combinations rather than emitting a gate that silently deadlocks.

**How stagr handles external code-quality/security tools (Sonar, Checkmarx, …).** stagr is a control
plane: it configures the *gate*, not the tool. Install the tool's **GitHub App** (org-level) so it
publishes its own **check-run** on the PR, then list that check's `name` **and** the App's numeric
`app_id` here. stagr never provisions or runs the tool; it simply **requires that check**. Identity is
**positive** — the check-run must match the exact name *and* be produced by that App id — so a same-name
check from any other App (including the repo's own `github-actions` jobs) cannot satisfy or forge it. (An
earlier draft accepted "any App that is not `github-actions`"; that negative rule is gone — a display name
is not an identity.) Find an App's id via the GitHub API (e.g. `GET /users/{app-slug}[bot]` → `id`, or the
App's settings). This is tool-agnostic by construction: list whatever check names/App ids your tools
publish. A scan you run inside your build (`build.commands`) is part of the `Validate` check instead and
must **not** be listed here. Only meaningful when `modules.auto_merge` is on.

> **`build.commands` are trusted operator shell.** They are emitted verbatim into the `Validate`
> workflow's `run:` block, so a GitHub expression such as `${{ secrets.NPM_TOKEN }}` is **allowed** there
> (for authenticated installs) — unlike labels, check names, globs, branches and secret names, which are
> workflow *literals* and reject `${{ … }}` and other breakout characters. The renderer never injects any
> untrusted PR field (title, body, branch, author) into build commands.

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

For an `anthropic` stage (Claude Code consumes a contract model), if none of layers 1–3 yields a
model, resolution **fails loudly** (see below) — there is no hidden built-in default, so the toolkit
never silently picks a model version. An `openai` stage (Codex) supplies its own model, so this rule
does not apply to it: an all-Codex graph is valid with no `defaults.models`.

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

**Example** — org sets the defaults; the review stage pins only its complex tier (the supported
pairing: Anthropic implement, OpenAI review):

```yaml
defaults:
  provider: anthropic
  models:
    anthropic: { default: "<anthropic-default>" }
    openai: { default: "<openai-default>", tiers: { complex: "<openai-complex>" } }
stages:
  - id: implement
    type: implement
    provider: anthropic                                       # -> <anthropic-default>
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

A preset pre-fills `build.commands` with the defaults below, which the rendered Validate workflow runs
verbatim. Override any per key by setting it under `build.commands`; `custom` pre-fills nothing.

| Preset | install | lint | test |
|---|---|---|---|
| `python` | `requirements.txt` if present, then `pip install -e .` for a `pyproject.toml`/`setup.py` | `ruff check .` | `python -m pytest` |
| `maven` | `mvn -q -N install` | `mvn -q spotless:check` | `mvn -q verify` |
| `gradle` | `./gradlew dependencies` | `./gradlew check -x test` | `./gradlew test` |
| `node` | `npm ci` | `npm run lint` | `npm test` |
| `go` | `go mod download` | `golangci-lint run` | `go test ./...` |
| `rust` | `cargo fetch` | `cargo clippy -- -D warnings` | `cargo test` |
| `dotnet` | `dotnet restore` | `dotnet format --verify-no-changes` | `dotnet test` |

---

## 5. Setup steps

> Install the CLI first (needs Python 3.10+). `stagr` is not on PyPI yet, so install from the
> repository's source archive (no `git` required):
> `pipx install "https://github.com/contactexepex/agentic-foundation/archive/refs/heads/main.tar.gz"`.
> For a reproducible install, pin the URL to a commit SHA or release tag instead of `main`. See
> [CLI.md](CLI.md) for full options.

> **Prerequisite — the Codex GitHub App (only for `openai` review/security stages).** A stage with
> `provider: openai` (the reviewer, which runs **Codex**) requires the **Codex GitHub App** to be
> installed on the repo/org and configured to review pull requests — that app performs the review and
> acts on the `@codex` comments the rendered workflows post. The two reviews run in sequence, never
> concurrently: `request-review.yml` re-requests the **code** review on each push (so it iterates as
> the PR changes), and once the code review has converged (completed + clean on the head)
> `final-security-review.yml` requests a **single security** review as the last step before merge.
> Without the app installed a PR can open with no review, so install/enable it **before** relying on
> the pipeline and confirm on a test PR that the reviews run.
>
> **Configure the App to auto-run the *code* review only on open — not the security review.** Whether
> the Codex App runs a security review automatically when a PR opens is a ChatGPT-side App setting the
> toolkit cannot render. Leave it **off**: if the App auto-runs a security review on open, it races the
> code review on every open and hits the same backend concurrency error the serialized flow exists to
> avoid. `final-security-review.yml` is the sole trigger of the security review, so the App only needs
> to review code on open; the workflow drives the single security review at the end.
> The `anthropic` implementer needs no GitHub App: it runs the pinned Claude Code action from
> `workflow_dispatch` and authenticates directly with the `ANTHROPIC_API_KEY` secret (`doctor` lists
> the exact secret NAMES your config needs).

1. Add `.agentic/config.yml`. The quickest way is `stagr init` (guided wizard) or
   `stagr init --profile <minimal|standard|full|custom>` (non-interactive), which writes a commented,
   valid starter for you; or write it by hand starting from a `profile`, a `platform`, and a model
   binding for any model-consuming stage, adding `stages` only for finer control. (An AI drafting
   *skill* that proposes a tailored config is a separate, roadmap item — M4.)
2. Run `stagr doctor` — it validates the config and lists the exact secret NAMES to create.
3. Create those secrets in your CI/SCM secret store (section 2), then run `stagr plan` to preview and
   `stagr apply` to render the pipeline for your `platform` into `.github/workflows/`.
4. Commit and merge the rendered workflows.

> **What renders today:** `apply` emits the core lane — the `Validate` check, the review router, the
> Claude implementer, (when a Codex review/security stage is configured) the Codex review +
> thread-cleanup lane, and (when `modules.auto_merge` is on) the fail-closed `auto-merge.yml` gate.
> **Not yet rendered:** other stage types (`plan`, `test`, `integration-test`, `docs`, `release`, and
> non-Codex reviewers) and the `modules.sonar` toggle (superseded by `merge.required_status_checks`) —
> they are declared and validated but do not yet emit workflows; that rendering is on the roadmap (see
> [CHARTER.md](CHARTER.md) §7). Always read `stagr plan` output — it lists the exact files that will be
> written — so a declared stage or module that does not yet render is visible before you commit.

---

## 6. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Reviewer never runs on Codex | `REMEDIATION_TOKEN` missing or not a real-user PAT. |
| Endpoints/agents fail auth | Model API key secret missing or wrong name. |
| Fast path never triggers | Change exceeds `routing.fast_path` size, or path is in `exclude`. |
| Wrong model tier chosen | Review `tiering.thresholds`; deterministic tiering keys off files/lines/paths only. |
| Auto-merge never fires | `modules.auto_merge` is `false`, or a gate signal (CI/review/threads) is not green. |
