# Stagr Neutral Core — Neutral Config Contract

**Status:** Design phase — not yet implemented

---

## Purpose

The neutral config contract is the interface between the **operator** (who configures
pipelines) and **Stagr** (which renders them). It lives entirely in `.agentic/config.yml`
and is platform-agnostic: it carries no GitHub syntax, no CI event names, no provider
API details, and no secret values.

---

## What belongs in the config

The config declares:

- **Stage identity** — what kind of work each stage does and which provider+backend
  performs it
- **Stage governance** — when a stage runs, whether it blocks merge, and which other
  stages it depends on
- **Pipeline policy** — routing (fast-path rules) and module flags (auto-merge)

The config does **not** contain:

- Provider API endpoints
- Secret **values** — the actual credential material is never in the config. Secret
  **names/aliases** (references that tell the renderer which secret to look up) are
  allowed; for example `auth.token_secret: REMEDIATION_TOKEN` names the platform secret
  without revealing its value. See `03-provider-backend-model.md` for the alias model.
- CI event names (`pull_request_target`, `issue_comment`, etc.)
- Comment formats or platform-specific selectors
- Any implementation detail that is specific to one platform or one provider version

---

## Config structure

```yaml
# .agentic/config.yml
version: 2

# Profile selects a named preset that supplies default field values for stages.
# "custom" means no built-in expansion — all stage fields are declared explicitly.
# See 02-canonical-stage-model.md for available profiles and expansion rules.
profile: custom

# Platform declaration. Identifies the target CI/CD platform and its settings.
# Required. The renderer uses this to select the correct PlatformRenderer.
platform:
  type: github              # target platform id (e.g. github, gitlab, bitbucket)
  default_branch: main      # branch the governance artifact targets for merges
  trusted_roles:            # AuthorRole[] for TrustPolicy
    - owner
    - member
    - collaborator
  labels:
    human_merge: human-merge  # label that forces the human-gated lane
  auth:
    token_secret: REMEDIATION_TOKEN  # platform secret name for the trusted-user token

# Pipeline-level defaults for provider and model (optional).
# Provides fallback values for stages that do not declare provider or model explicitly.
# Applied during backend/model default resolution (see 02-canonical-stage-model.md),
# after profile expansion and before per-provider backend defaults from the registry.
defaults:
  provider: anthropic         # fallback provider id for stages with no provider field
  models:
    anthropic:
      default: claude-opus-5-5  # fallback model for this provider; null = backend default

# Pipeline-level routing policy.
# Renderer translates this into a native path classifier.
routing:
  fast_path:
    enabled: false          # true enables a bypass lane for trivial changes
    match:
      paths:                # glob patterns; required when enabled: true
        - "docs/**"
        - "*.md"
    stages:
      fast:   []            # stage ids that run on the FAST route
      normal: []            # stage ids that run on the NORMAL route (all eligible stages)

# Module flags enable optional Stagr-managed or Stagr-observed components.
modules:
  auto_merge: true          # enable the auto-merge governance component

# What "green" means for this repository: the commands of the build and unit-test
# stages (see 09-check-stages.md). A preset fills every command it can.
build:
  preset: maven             # python | maven | gradle | node | go | rust | dotnet | custom
  # commands:               # optional per-key overrides: install, build, lint, typecheck, test

# Stage declarations.
stages:
  - id: review              # stable identifier, unique within the config
    type: review            # StageKind (see canonical-stage-model.md)
    provider: openai        # API/credential provider id
    backend: codex          # invocation mechanism (defaults per provider)
    # model: gpt-4o         # optional; omit to use the backend's default
    skill: code-review      # skill id → .agentic/skills/<id>/SKILL.md
    gate: blocking          # blocking | advisory (default blocking)
    triggers:               # StageTrigger[]: when this stage runs
      - pr_opened
      - pr_updated
    depends_on: []          # stage ids that must reach conclusion=PASS before this starts

  - id: security
    type: security
    provider: openai
    backend: codex
    skill: security-review
    gate: blocking
    triggers:
      - pr_opened
      - pr_updated
    depends_on: [review]    # starts after the code review has passed

  # Check stages have no provider, backend or skill (see 09-check-stages.md):
  # a managed one runs commands on a CI job Stagr renders, an observed one reads a
  # named result from a named producer. Neither takes secrets. gate defaults to blocking.
  - id: integration-test
    type: custom
    commands: ["./scripts/integration.sh"]   # custom stages only
    timeout_minutes: 30                      # 1..360, default 30
    # triggers omitted: runs on pr_opened and pr_updated
    gate: advisory
  - id: analysis
    type: custom
    observe: { check: "Code Analysis", producer: 12526 }   # GitHub App id of the tool that posts it

  # A stage with enabled: false is excluded before normalization — not rendered,
  # not in the dependency graph, not in blockingStageIds. See 02-canonical-stage-model.md.
  - id: implement-codex
    type: implement
    provider: openai
    enabled: false          # optional; true by default
    triggers:
      - issue_labeled
```

### Config keys and the normalized model

The config uses the vocabulary of `stagr/config.schema.json`; normalization translates it into
the model of `02-canonical-stage-model.md`. This table is the only place the two are mapped.

| Config key | Normalized model |
|---|---|
| `type: review` (lowercase) | `kind: REVIEW` |
| `depends_on: [ids]` | `dependencies: string[]` |
| `gate: blocking` / `gate: advisory` | `StageGate.BLOCKING` / `StageGate.NON_BLOCKING` |
| `triggers: [pr_opened, ...]` | `StageTrigger[]` |
| `provider`, `backend`, `model`, `skill` | `AgentExecutor` |
| `commands`, `timeout_minutes` | `CommandsExecutor` |
| `observe: { check, producer }` | `ObservedExecutor` |

### Module flags

The `modules:` key enables optional Stagr-managed components. All flags default to
`false`. Recognized V1 module flags:

| Flag | Default | Meaning |
|---|---|---|
| `auto_merge` | `false` | Enables the auto-merge governance component. The governance artifact merges automatically when all merge gate conditions are satisfied. |

An external check such as SonarCloud is not a module: it is an observed stage
(`09-check-stages.md`).

Sub-fields of `modules:` not listed above are unrecognized and produce a validation
error. The "silently ignored" rule for unrecognized keys applies only to unknown
**top-level** keys (see "Non-Stagr keys" below); it does not extend to sub-fields of
a recognized Stagr namespace.

### Non-Stagr keys

`.agentic/config.yml` is owned by the operator, not exclusively by Stagr. Operators may
include additional top-level keys alongside the Stagr contract to co-locate CI or tooling
configuration in a single file. For example:

```yaml
# Operator tooling configuration — not part of the Stagr contract.
# Stagr ignores this key during validation and rendering.
deploy:
  target: staging
```

Stagr validates only the keys it defines (`version`, `profile`, `platform`, `defaults`,
`routing`, `modules`, `stages`, `providers`, and `build`). Any unrecognized top-level key is
silently ignored by `stagr plan` and `stagr apply`. This lets operators co-locate other
tooling configuration in `.agentic/config.yml` without breaking Stagr validation.

---

## Minimal config

An operator need only specify fields that differ from defaults. The renderer and profile
expansion (see `02-canonical-stage-model.md`) fill in the rest. The minimal valid config
for the baseline pipeline (build, unit-test, review, security) using the `standard` profile:

```yaml
version: 2
profile: standard
platform:
  type: github
  default_branch: main
build:
  preset: maven
modules:
  auto_merge: true
```

When `backend` is omitted on an agent stage, the renderer applies the default backend for the given
`provider` (e.g., `openai` → `codex`). See `03-provider-backend-model.md`.

---

## Schema versioning

The `version` field is the config schema version, not a Stagr release version. Breaking
schema changes increment it. A Stagr CLI that does not support the declared version must
refuse to render and report a clear error.
