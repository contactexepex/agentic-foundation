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

- Provider API endpoints or authentication details
- Secret names or values (secrets are resolved by the renderer from environment
  configuration — see `03-provider-backend-model.md`)
- CI event names (`pull_request_target`, `issue_comment`, etc.)
- Comment formats or platform-specific selectors
- Any implementation detail that is specific to one platform or one provider version

---

## Config structure

```yaml
# .agentic/config.yml
version: "1"

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

# Module flags enable optional Stagr-managed components.
modules:
  auto_merge: true          # enable the auto-merge governance component

# Stage declarations.
stages:
  - id: review              # stable identifier, unique within the config
    type: review            # StageKind (see canonical-stage-model.md)
    provider: openai        # API/credential provider id
    backend: codex          # invocation mechanism (defaults per provider)
    # model: gpt-4o         # optional; omit to use the backend's default
    skill: code-review      # skill id → .agentic/skills/<id>/SKILL.md
    gate: blocking          # StageGate: blocking | non_blocking
    triggers:               # StageTrigger[]: when this stage runs
      - pr_opened
      - pr_updated
    dependencies: []        # stage ids that must reach conclusion=PASS before this starts

  - id: security
    type: security
    provider: openai
    backend: codex
    skill: security-review
    gate: blocking
    triggers:
      - pr_opened
      - pr_updated
    dependencies: []        # independent of 'review' — both start on every push
```

---

## Minimal config

An operator need only specify fields that differ from defaults. The renderer and profile
expansion (see `02-canonical-stage-model.md`) fill in the rest. The minimal valid config
for a two-stage review pipeline:

```yaml
version: "1"
modules:
  auto_merge: true
stages:
  - id: review
    type: review
    provider: openai
    skill: code-review
    gate: blocking
    triggers: [pr_opened, pr_updated]
  - id: security
    type: security
    provider: openai
    skill: security-review
    gate: blocking
    triggers: [pr_opened, pr_updated]
```

When `backend` is omitted, the renderer applies the default backend for the given
`provider` (e.g., `openai` → `codex`). See `03-provider-backend-model.md`.

---

## Schema versioning

The `version` field is the config schema version, not a Stagr release version. Breaking
schema changes increment it. A Stagr CLI that does not support the declared version must
refuse to render and report a clear error.
