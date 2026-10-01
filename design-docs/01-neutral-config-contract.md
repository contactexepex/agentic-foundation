# Stagr Neutral Core — Neutral Config Contract

**Status:** Target design. What is built today is in
[ARCHITECTURE.md, section 8](../docs/ARCHITECTURE.md#8-status--roadmap).

---

## Purpose

The neutral config contract is the interface between the **operator** (who configures
pipelines) and **Stagr** (which renders them). It lives entirely in `.agentic/config.yml`
and is platform-agnostic: it carries no platform syntax, no CI event names, no provider
API details, and no secret values.

---

## What belongs in the config

The config declares:

- **Stage identity** — what kind of work each stage does and which provider+backend
  performs it
- **Stage governance** — when a stage runs, whether it blocks the gate result, and which other
  stages it depends on
- **Pipeline policy** — routing (fast-path rules) and the gate rule for review discussions

The config does **not** contain:

- Provider API endpoints
- Secret **values** — the actual credential material is never in the config. Secret
  **names/aliases** (references that tell the renderer which secret to look up) are
  allowed; for example `auth.token_secret: REMEDIATION_TOKEN` names the platform secret
  without revealing its value. See `03-provider-backend-model.md` for the alias model.
- CI event names
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

# Platform declaration: the two platform axes and their settings (see "The platform block").
platform:
  scm: github               # required: where changes, the gate and identities live
  ci: github                # optional: where jobs run; defaults to scm
  # host: https://github.acme.com   # optional; self-hosted only
  trusted_roles:            # AuthorRole[] for TrustPolicy (redesigned in Plan B)
    - owner
    - member
    - collaborator
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
    globs:                  # glob patterns for the FAST route
      - "docs/**"
      - "*.md"
    stages:
      fast:   []            # stage ids that run on the FAST route
      normal: []            # stage ids that run on the NORMAL route (all eligible stages)

# Gate policy (MergePolicy). The gate's blocking stages come from each stage's `gate`.
merge:
  discussions:
    require_resolved: true  # every open review discussion must be resolved for the gate to pass

# What "green" means for this repository: the commands of the build stage, unit tests
# included (see 09-check-stages.md). A preset fills every command it can.
build:
  preset: maven             # python | maven | gradle | node | go | rust | dotnet | custom
  # commands:               # optional per-key overrides: install, build, lint, typecheck, test

# Stage declarations.
stages:
  - id: review              # stable identifier, unique within the config
    type: review            # StageKind (see canonical-stage-model.md)
    provider: openai        # API/credential provider id
    backend: codex          # invocation mechanism (defaults per provider)
    # model: { default: gpt-4o }   # optional; omit to use the backend's default
    skill: code-review      # skill id → shipped skill, or the repo's .agentic/skills/<id>/SKILL.md
    gate: blocking          # blocking | advisory (default blocking)
    triggers:               # StageTrigger[]: when this stage runs
      - change_opened
      - change_updated
    depends_on: []          # stage ids that must reach conclusion=PASS before this starts

  - id: security
    type: security
    provider: openai
    backend: codex
    skill: security-review
    gate: blocking
    triggers:
      - change_opened
      - change_updated
    depends_on: [review]    # starts after the code review has passed

  # Check stages have no provider, backend or skill (see 09-check-stages.md):
  # a managed one runs commands on a CI job Stagr renders, an observed one reads a
  # named result from a named producer. Neither takes secrets. gate defaults to blocking.
  - id: integration-test
    type: custom
    commands: ["./scripts/integration.sh"]   # custom stages only
    timeout_minutes: 30                      # 1..360, default 30
    # triggers omitted: runs on change_opened and change_updated
    gate: advisory
  - id: analysis
    type: custom
    # producer: the identity of the tool that posts the result (09, section 2)
    observe: { check: "Code Analysis", producer: 12526 }

  # A stage with enabled: false is excluded before normalization — not rendered,
  # not in the dependency graph, not in blockingStageIds. See 02-canonical-stage-model.md.
  - id: extra-review
    type: review
    provider: openai
    enabled: false          # optional; true by default
    triggers:
      - manual
```

### Config keys and the normalized model

The config uses the vocabulary of `stagr/config.schema.json`; normalization translates it into
the model of `02-canonical-stage-model.md`. This table is the only place the two are mapped.

| Config key | Normalized model |
|---|---|
| `type: review` (lowercase) | `kind: REVIEW` |
| `depends_on: [ids]` | `dependencies: string[]` |
| `gate: blocking` / `gate: advisory` | `StageGate.BLOCKING` / `StageGate.NON_BLOCKING` |
| `triggers: [change_opened, ...]` | `StageTrigger[]` |
| `provider`, `backend`, `model`, `skill` | `AgentExecutor` |
| `commands`, `timeout_minutes` | `CommandsExecutor` |
| `observe: { check, producer }` | `ObservedExecutor` |

### The schema is the key list

`stagr/config.schema.json` lists exactly the keys the neutral pipeline reads, and nothing
else. The top-level keys are `version`, `profile`, `platform`, `defaults`, `providers`,
`stages`, `routing`, `merge` and `build`. An external check such as SonarCloud is an observed
stage (`09-check-stages.md`), not a separate key.

**An unknown key is a validation error at every level**, top level included (#265, section 2,
decision 12). `.agentic/config.yml` holds only the Stagr contract; other tools keep their
configuration in their own files. V-S01 (`07-validation.md`) checks this rule.

`backend` is a plain string. When it is omitted, the default comes from the stage's
provider (`openai` → `codex`).

### The platform block

`platform:` names the two platform axes (#265, section 2, decision 3; addendum, decision 22):

- `scm` (required) — where changes, the gate and identities live.
- `ci` (optional) — where jobs run. It defaults to `scm`.
- `host` (optional) — the base URL of a self-hosted platform. Omit it for the hosted service.

There is no `platform.type` key. Platform-specific settings, such as `trusted_roles` and `auth`,
stay under `platform:` and are checked against the chosen platform; an unknown key fails. V-S17
(`07-validation.md`) checks that `scm` and `ci` name a platform with a renderer.

---

## Minimal config

An operator need only specify fields that differ from defaults. The renderer and profile
expansion (see `02-canonical-stage-model.md`) fill in the rest. The minimal valid config
for the baseline pipeline (build, review, security) using the `standard` profile:

```yaml
version: 2
profile: standard
platform:
  scm: github
build:
  preset: maven
```

When `backend` is omitted on an agent stage, the renderer applies the default backend for the given
`provider` (e.g., `openai` → `codex`). See `03-provider-backend-model.md`.

---

## Schema versioning

The `version` field is the config schema version, not a Stagr release version. Breaking
schema changes increment it. A Stagr CLI that does not support the declared version must
refuse to render and report a clear error.
