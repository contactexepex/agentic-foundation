# Configuring agentic-foundation

This is the complete setup reference: what the toolkit needs, the exact secret/variable names, which
credentials must be a **service account** vs a **personal access token (PAT)**, and every field of
`.agentic/config.yml`.

---

## 1. Prerequisites

- A GitHub repository you can add workflows and secrets to.
- Provider access for each role you configure (Claude and/or OpenAI/Codex).
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

> If a role uses Claude for **review** (not the `@codex` flow), you do **not** need
> `CODEX_REMEDIATION_TOKEN` — Claude review runs via its action with `ANTHROPIC_API_KEY`. The
> installer tells you exactly which secrets your chosen `roles` require.

---

## 3. `.agentic/config.yml` — field reference

Copy `templates/config/agentic.config.yml.tmpl` to `.agentic/config.yml`. It is validated against
`install/config.schema.json`.

**Simple by default, advanced when you want it.** The only required keys are `version` and `roles`
(each role needs a `provider`). Everything else is optional and falls back to a documented default,
so a minimal config is a few lines; add more blocks only to take finer control.

```yaml
# Minimal config — models resolve from defaults/org, no build gate.
version: 1
roles:
  implementer: { provider: claude }
  reviewer:    { provider: openai }
```

### `repository`
| Field | Meaning |
|---|---|
| `default_branch` | Trunk branch PRs target. |
| `trusted_authors` | GitHub `author_association` values allowed to drive agentic changes (`OWNER`, `MEMBER`, `COLLABORATOR`, `CONTRIBUTOR`). |
| `same_repo_only` | `true` = ignore fork PR heads. Keep `true` unless you accept fork contributions (widens the threat model). |

### `labels`
| Field | Meaning |
|---|---|
| `human_merge` | A PR with this label is **never** auto-merged (human keeps merge authority). |
| `dispatch` | Optional label that dispatches an implementation task from an issue. |

### `defaults` (optional — org/account fallbacks)
| Field | Meaning |
|---|---|
| `models.{claude,openai}.default` | Default model ID for that provider when a role does not set its own. Keep it here or seed it from an org-level shared config. |
| `models.{claude,openai}.tiers.{trivial,standard,complex}` | Per-tier default model for that provider, used when `tiering.enabled: true`. |

### `roles.implementer` / `roles.reviewer`
| Field | Meaning |
|---|---|
| `provider` | `claude` or `openai` — **the only required field per role.** The two roles are independent — mix freely, including the same provider with different models. |
| `model` (optional) | Omit it to inherit from `defaults.models.<provider>`. Set it to override for this repo. **Placeholders only in the template** — set your provider's current IDs; the toolkit never hardcodes model versions. |
| `model.default` (optional) | Override the resolved default model for this role. |
| `model.tiers.{trivial,standard,complex}` (optional) | Override the per-tier model for this role. Set just one tier and the rest still inherit. |

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
| `preset` | `python \| maven \| gradle \| node \| go \| rust \| dotnet \| custom`. Pre-fills `commands` from `templates/presets/`. |
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

---

## 3a. Model resolution

Each role's model is resolved per run, **most specific wins**. For a given role and change tier the
toolkit walks this chain and uses the first model it finds:

| # | Layer | Where it comes from |
|---|---|---|
| 1 | **Per-request override** | A model supplied at dispatch time (a `workflow_dispatch` input or a dispatch-comment command). Wins over everything. |
| 2 | **Per-repo role model** | `roles.<role>.model.tiers.<tier>`, then `roles.<role>.model.default`. |
| 3 | **Org/account default** | `defaults.models.<provider>.tiers.<tier>`, then `defaults.models.<provider>.default`. |
| 4 | **Toolkit fallback** | The documented built-in for that provider. |

Key points:

- **Provide a model → it overrides the default.** Set one at any layer to override every layer below
  it; leave it unset to inherit. You can override just one tier (e.g. `complex`) and let the rest
  inherit.
- **Tier** (`trivial` / `standard` / `complex`) comes from the deterministic classifier (change size
  + paths) only when `tiering.enabled: true`; otherwise `default` is used.
- **Fail loudly, never guess.** If no model resolves for a role/tier, the installer/run stops with a
  clear error naming the role and which key to set — it never silently picks a model version.

**Example** — org sets the defaults; one repo pins only its reviewer's complex tier:

```yaml
defaults:
  models:
    claude: { default: "<claude-default>" }
    openai: { default: "<openai-default>", tiers: { complex: "<openai-complex>" } }
roles:
  implementer: { provider: claude }                         # -> <claude-default>
  reviewer:
    provider: openai
    model: { tiers: { complex: "<openai-strong>" } }        # complex -> <openai-strong>; else <openai-default>
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

1. Add `.agentic/config.yml` (edit the template, or let the Claude skill draft it).
2. Create the secrets your `roles` require (section 2). The installer lists the exact set.
3. Run the installer / invoke the skill — it validates the config, renders the enabled modules'
   workflows into `.github/workflows/`, and opens a bootstrap PR.
4. Merge the bootstrap PR.

---

## 6. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Reviewer never runs on Codex | `CODEX_REMEDIATION_TOKEN` missing or not a real-user PAT. |
| Endpoints/agents fail auth | Model API key secret missing or wrong name. |
| Fast path never triggers | Change exceeds `routing.fast_path` size, or path is in `exclude`. |
| Wrong model tier chosen | Review `tiering.thresholds`; deterministic tiering keys off files/lines/paths only. |
| Auto-merge never fires | `modules.auto_merge` is `false`, or a gate signal (CI/review/threads) is not green. |
