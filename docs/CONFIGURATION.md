# Configuring agentic-foundation

This is the setup reference: what the toolkit needs, the exact secret names, which credentials must be
a **service account** vs a **personal access token (PAT)**, and every field of `.agentic/config.yml`.

---

## 1. Prerequisites

- A repository on GitHub that you can add workflows and secrets to. GitHub is the only platform with
  a renderer today.
- Provider access for each provider your stages use (Claude or OpenAI Codex).

The toolkit never creates credentials.

---

## 2. Credentials — names, type, and scope

Set these as **repository (or environment) secrets** unless noted otherwise. Names are the defaults;
you can rename them in the config (see below).

| Purpose | Name | Type | Required when | Scope / notes |
|---|---|---|---|---|
| Claude model access | `ANTHROPIC_API_KEY` | **Service account** (dedicated API key) | any stage uses `provider: anthropic` | Never a personal key. Rotate independently. |
| OpenAI model access (roadmap) | `OPENAI_API_KEY` | **Service account** (dedicated API key) | **Not required today** — `openai` runs Codex, which is app-backed and supplies its own model. Reserved for a future model-consuming OpenAI backend. | Never a personal key. |
| Codex comment-trigger / PR publication | `REMEDIATION_TOKEN` | **Fine-grained PAT (real user)** | a stage uses Codex's `@codex` comment flow | Least scope: **Contents: R/W** + **Pull requests: R/W**. **No** admin/merge. Must be a real, attributable user — bot/App tokens do not reliably trigger `@codex`. |
| Stagr GitHub App private key | `STAGR_APP_PRIVATE_KEY` | GitHub App private key | you configure `platform.publisher` | See [Publisher](#publisher-stagr-github-app). |
| GitHub API (PR reads) | `GITHUB_TOKEN` | Provided by Actions | always | No action needed; each generated workflow sets its own least-privilege permissions. |

**Why the split (PAT vs service account):**
- **Model API keys** (today `ANTHROPIC_API_KEY`; `OPENAI_API_KEY` is roadmap — Codex supplies its own
  model) are machine credentials for paid model usage — use dedicated **service-account** keys so cost
  and access are isolated from any person and can be rotated without touching a human account.
- **`REMEDIATION_TOKEN`** must be a **real-user PAT** because Codex acts on `@codex` commands
  only from an attributable user. Grant it the minimum (Contents + Pull requests, R/W) — it needs no
  permission to merge or administer.

> Secret names are configurable. The names above are defaults; override them per provider with
> `providers.<provider>.api_key_secret` and per platform with `platform.auth.token_secret`.

---

## 3. `.agentic/config.yml` — field reference

Write `.agentic/config.yml` by hand and keep it valid against
[`stagr/config.schema.json`](https://raw.githubusercontent.com/contactexepex/agentic-foundation/main/stagr/config.schema.json).
The schema lists exactly the keys the toolkit reads; a key that is not listed does nothing.

- An **unknown key inside a Stagr key** (`platform`, `defaults`, `stages`, ...) is an error.
- An **unknown top-level key** is ignored, not rejected, so you can keep your own tooling settings in
  the same file.

**Simple by default, advanced when you want it.** A runnable config needs a `version` (always `2`), a
`profile` (default `standard`, which expands to a stage graph), a `platform` (defaults to GitHub), and
`platform.publisher.app_id`, the ID of your Stagr GitHub App, which `stagr plan` and `stagr apply`
require (see [Publisher](#publisher-stagr-github-app)). That is a few lines; add `stages` and other
blocks only to take finer control. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the design.

```yaml
# Minimal config — the profile expands to a stage graph.
version: 2
profile: standard
platform: { type: github, publisher: { app_id: 123456 } }
```

### `profile`
| Field | Meaning |
|---|---|
| `profile` | Onboarding shortcut that expands to a default stage graph: `minimal` (a code `review` stage), `standard` (`review` + `security`), or `custom` (no stages — you define them all under `stages`). Default `standard`. The `review` and `security` stages are independent: neither waits for the other. Stages you list under `stages` are merged on top (same id overrides). |

### `platform`
| Field | Meaning |
|---|---|
| `type` | `github`. Selects the renderer. Only the GitHub renderer exists today, so `github` is the only accepted value. Default `github`. |
| `same_repo_only` | `true` = ignore fork PR/MR heads. Keep `true` unless you accept fork contributions (widens the threat model). Default `true`. |
| `trusted_roles` | Normalized permission levels allowed to drive agentic changes (`owner`, `member`, `collaborator`, `contributor`); the renderer maps them to the platform's own roles. Default `owner`, `member`, `collaborator`. |
| `auth.token_secret` | **Name** of the secret holding the platform API token. Never the value. |
| `publisher.app_id` | Optional. The numeric ID of the **Stagr GitHub App** that publishes Stagr's own Check Runs. A positive whole number (quoted digits also work). It is **not a secret**: it is written as-is into the generated workflows. No default. **Required by `stagr plan` and `stagr apply`**: the generated workflows publish their check runs as this App. |
| `publisher.private_key_secret` | Optional, used with `publisher`. The **name** of the repository secret that holds the App's private key. Default `STAGR_APP_PRIVATE_KEY`. Never the key itself. |
| `labels.human_merge` | A change-request with this label is **never** merged automatically (a human keeps merge authority). Default `human-merge`. |

A secret name is letters, digits and underscores, not starting with a digit, and not starting with
`GITHUB_` (GitHub reserves that prefix). The same rule applies to every secret-name field below.

### `defaults` (optional — fallbacks for stages)
| Field | Meaning |
|---|---|
| `provider` | Default provider id for stages that omit one. If a stage has no provider and there is no default, validation fails. |
| `models.<provider>.default` | Default model ID for that provider when a stage does not set its own. `<provider>` is any provider id. |

### `providers` (optional — secret names per provider)
| Field | Meaning |
|---|---|
| `providers.<provider>.api_key_secret` | **Name** of the secret holding the API key. Lets you use your own secret naming. Never the key value. |
| `providers.<provider>.secrets.<alias>` | Maps a semantic alias used by the backend (e.g. `PROVIDER_API_KEY`, `TRUSTED_COMMENTER_TOKEN`) to the actual repository secret name. See **Secret alias resolution** below. |

#### Secret alias resolution

When the toolkit writes `env:` entries into generated workflow YAML it resolves each backend-declared
alias to a concrete CI secret name using the following precedence (first match wins):

1. **Explicit map** — `providers.<provider>.secrets.<alias>` in your config.
2. **Established defaults** — two semantic aliases are resolved from existing config fields before the
   convention applies:
   - `PROVIDER_API_KEY` → `providers.<provider>.api_key_secret` if set, otherwise the provider's built-in
     default (`ANTHROPIC_API_KEY` for `anthropic`, `OPENAI_API_KEY` for `openai`).
   - `TRUSTED_COMMENTER_TOKEN` → `platform.auth.token_secret` if set, otherwise `REMEDIATION_TOKEN`.
3. **Convention** — any other alias is used as the secret name directly (alias == secret name).

Example — rename the Anthropic key secret and use a custom PAT:

```yaml
providers:
  anthropic:
    secrets:
      PROVIDER_API_KEY: MY_ANTHROPIC_KEY   # overrides the ANTHROPIC_API_KEY default
platform:
  auth:
    token_secret: MY_GITHUB_PAT            # overrides the REMEDIATION_TOKEN default
```

#### Publisher (Stagr GitHub App)
Stagr publishes its own Check Runs as a GitHub App, not with a personal token. You create the App
yourself and store its private key as a repository secret; the config only names them:

```yaml
platform:
  publisher:
    app_id: 123456                          # the App's numeric ID (not a secret)
    private_key_secret: STAGR_APP_PRIVATE_KEY   # NAME of the secret holding the App private key
```

Steps for the operator: create the GitHub App, install it on the repository, save its private key as a
repository secret with the name you put in `private_key_secret`, and set `app_id`.

Give the App these repository permissions (without them the generated workflows fail with
authorization errors):

| Permission | Access | Why |
|---|---|---|
| Checks | Read and write | Create and update the stage Check Runs; the merge gate reads them |
| Pull requests | Read | Read pull requests, changed files and review threads |
| Issues | Read | Read pull request comments, where review backends post their results |
| Metadata | Read | Granted automatically |

A value that is not a valid secret name (for example a pasted key) is rejected when the config is
validated, and the rejected value is never echoed. The private key gives access wherever the App is
installed, so guard it and rotate it if it leaks.

### `stages` (optional — the agent graph)
Omit to use the profile's stages. Anything you list is **merged onto** the profile (a stage with the
same `id` overrides). Each stage is one agent. Two providers have a default backend today: `anthropic`
(Claude Code) and `openai` (Codex).

| Field | Meaning |
|---|---|
| `id` | **Required.** Unique stage id (`^[a-z0-9][a-z0-9-_]*$`), e.g. `review`, `security`. |
| `type` | **Required.** `review` \| `security` \| `build` \| `test` \| `custom` \| `implement`. |
| `enabled` | `false` to keep a stage defined but off. Default `true`. |
| `provider` | **The primary knob.** `anthropic` runs Claude Code; `openai` runs Codex. Omit to inherit `defaults.provider`. |
| `backend` | Optional. The tool that performs the stage, as a plain string. Omit it: the default follows the provider (`anthropic` → `claude-code-action`, `openai` → `codex`). |
| `model.default` | Optional model ID for this stage; overrides `defaults.models.<provider>.default`. |
| `skill` | Skill id. The stage's methodology lives in `.agentic/skills/<id>/SKILL.md`, and validation fails if that file is missing. Starter skills ship under `stagr/templates/skills/`: `code-review` and `security-review`. |
| `triggers` | Any of `pr_opened`, `pr_updated`, `manual`, `issue_labeled`. |
| `gate` | `advisory` (reported, never blocks merge) or `blocking` (the merge gate requires the stage to pass). Omit for `advisory`. |
| `depends_on` | Ids of stages that must pass before this one starts (defines the graph). Unknown ids and cycles are rejected. |

> **What renders today.** The GitHub renderer renders stages whose backend is started by a PR comment,
> such as Codex (`openai`). A backend that needs a different start, such as the Claude Code backend
> (`anthropic`, started as a CI component), is rejected by validation V-S08 on GitHub. So `implement`
> stages cannot be rendered yet. The only backends today are `claude-code-action` and `codex`.

See **Model resolution** below for how a stage's model is chosen.

### `routing.fast_path`
| Field | Meaning |
|---|---|
| `enabled` | `false` disables the fast path so every PR (docs included) is routed to every stage. Default `true`. |
| `globs` | A PR takes the fast path only when **every** changed file matches at least one of these globs. |
| `stages.fast` | Stage ids that run when a PR qualifies for the fast path. |
| `stages.normal` | Stage ids that run for all other PRs. |

Each of `stages.fast` and `stages.normal` must be **dependency-closed** (validation V-S09): if a listed
stage has a `depends_on` entry, that entry must be in the same list.

Set `enabled: false` when every change must go through review — e.g. a shared toolkit whose
documentation other people depend on. This repository does exactly that.

### `merge`
| Field | Meaning |
|---|---|
| `discussions.require_resolved` | When `true`, all open review discussions must be resolved before the merge gate passes. Default `false` (discussion state is not checked). |

---

## 3a. Model resolution

A stage's model is resolved once, **most specific wins**:

1. `stages[].model.default`
2. `defaults.models.<provider>.default`, where `<provider>` is the stage's provider (or
   `defaults.provider` when the stage names none).

If neither is set, no model is bound and the backend decides. `openai` (Codex) is app-backed and
supplies its own model, so a Codex stage normally needs no model at all. A model value is a literal
model ID; the toolkit does not rewrite it.

---

## 3b. Secret handling (non-negotiable)

The toolkit treats every credential as write-only and invisible:

- **Never logged, never printed, never echoed.** No secret — API key, token, username, or password —
  is written to workflow logs, step output, PR/issue comments, review text, error messages, or any
  artifact. Commands that could surface a secret are masked or avoided.
- **Passed only to the step that needs it,** via GitHub Actions secrets / `env`, scoped to the
  minimal job — never interpolated into a shell string that gets logged, and never persisted to disk.
- **The toolkit never creates or stores credentials.** The config names a secret; it never holds the
  value.
- **No secret in config.** `.agentic/config.yml` holds only non-sensitive settings and secret
  **names**; credentials live in repo/environment secrets (section 2). Do not put tokens in the config
  file.

If you ever see a secret value in a log or comment, treat it as compromised and rotate it.

---

## 4. Setup steps

> **Prerequisite — the Codex GitHub App (only for `openai` stages).** A stage with `provider: openai`
> runs **Codex**, which requires the **Codex GitHub App** to be installed on the repo/org and
> configured to review pull requests — that app performs the review and acts on the `@codex` comments
> the generated workflows post. Install it **before** relying on the pipeline and confirm on a test PR
> that the reviews run.

1. Add `.agentic/config.yml` (section 3), starting from a `profile` and a `platform`, and adding
   `stages` only for finer control. Put each `skill` a stage names at `.agentic/skills/<id>/SKILL.md`;
   the starter skills, `code-review` and `security-review`, are the folders under
   [`stagr/templates/skills/`](https://github.com/contactexepex/agentic-foundation/tree/main/stagr/templates/skills)
   in this repository (they also ship inside the installed package, next to the `stagr` module). Copy
   them into `.agentic/skills/`; `stagr plan` fails with V-S06 for any stage whose skill file is missing.
2. Create the secrets your providers need (section 2) in your CI/SCM secret store.
3. Create the Stagr GitHub App and its private-key secret, and put the App's ID in
   `platform.publisher.app_id` ([Publisher](#publisher-stagr-github-app)).
4. Run `stagr plan` to validate the config and list the workflow files it produces (it writes
   nothing), then `stagr apply` to write them into `.github/workflows/`. Commit the result. See
   [CLI.md](CLI.md).

---

## 5. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Reviewer never runs on Codex | `REMEDIATION_TOKEN` missing or not a real-user PAT, or the Codex GitHub App is not installed. |
| Endpoints/agents fail auth | Model API key secret missing or wrong name. |
| Fast path never triggers | A changed file matches none of `routing.fast_path.globs`. |
| Config rejected with a secret-name error | A `*_secret` field holds something that is not a valid secret name (for example a pasted token). Put the value in a CI secret and use its name. |
