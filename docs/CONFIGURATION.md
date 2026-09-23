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

### `roles.implementer` / `roles.reviewer`
| Field | Meaning |
|---|---|
| `provider` | `claude` or `openai`. The two roles are independent — mix freely, including the same provider with different models. |
| `model.default` | The model ID for this role. **Placeholders only in the template** — set your provider's current IDs; the toolkit never hardcodes model versions. |
| `model.tiers.{trivial,standard,complex}` | Model IDs per change tier, used when `tiering.enabled: true`. |

### `tiering`
| Field | Meaning |
|---|---|
| `enabled` | Turn dynamic model selection on/off. |
| `classifier` | `deterministic` (v1). Tier comes from change size + paths — no extra model call. |
| `thresholds.trivial` | `max_files`, `max_lines`, `only_paths` — a change within these is `trivial`. |
| `thresholds.complex` | `min_files`, `min_lines` — a change at/above these is `complex`. Anything in between is `standard`. |

### `build`
| Field | Meaning |
|---|---|
| `preset` | `python \| maven \| gradle \| node \| go \| rust \| dotnet \| custom`. Pre-fills `commands` from `templates/presets/`. |
| `commands.{install,lint,test,typecheck}` | What "green" means for this repo. The workflows run exactly these. Override any preset value. |

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
