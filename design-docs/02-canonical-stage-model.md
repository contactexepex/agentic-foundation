# Stagr Neutral Core — Canonical Stage Model

**Status:** Design phase — not yet implemented

---

## Overview

The canonical stage model is the fully normalized, platform-agnostic representation of
every stage in the pipeline. It is produced by Stagr after profile expansion and
dependency normalization, and it is the single source of truth that all renderers
receive. Renderers translate it; they never modify or extend it.

---

## Enumerations

### StageKind

The kind of work a stage performs. Determines which BackendRenderer handles the stage.

| Value | Semantics |
|---|---|
| `REVIEW` | Code-quality review by a model-backed provider. Completes when the reviewer finishes processing the head commit; findings may be present. |
| `SECURITY` | Security-focused review. Same completion semantics as REVIEW. Runs independently of REVIEW unless explicitly declared otherwise in `dependencies`. |
| `BUILD` | Compile/package step. Completes when the build finishes; conclusion is PASS only when the build succeeds. |
| `TEST` | Automated test run. Completes when tests finish; conclusion is PASS only when all tests pass. |
| `DEPLOY` | Deployment step. Environment-specific semantics. |
| `CUSTOM` | Operator-defined. Semantics declared by the referenced skill. |

### StageGate

Controls whether a stage's conclusion must be PASS before the merge gate passes.

| Value | Semantics |
|---|---|
| `BLOCKING` | The merge gate requires this stage to have reached conclusion=PASS on the current head SHA before the PR can merge. |
| `NON_BLOCKING` | The stage runs and its result is reported, but the merge gate does not wait for it. |

`MergePolicy.blockingStageIds` is derived at normalization time as the list of all
stage IDs where `gate == BLOCKING`. It is never re-derived at render time or run time.

### StageTrigger

When a stage's execution is requested.

| Value | Semantics |
|---|---|
| `PR_OPENED` | Fires when a PR transitions to an open, non-draft state. |
| `PR_UPDATED` | Fires on every push to an open, non-draft PR. |
| `MANUAL` | Fires only when explicitly triggered (e.g., a human command). |

> **V1 scope:** `SCHEDULED` is excluded from V1. It requires a `ScheduleSpec` on
> `NormalizedStage` (cron expression, timezone, etc.) that is not yet modeled. Any
> periodic retry/sweep logic needed by a renderer must be implemented inside the
> generated platform artifact as a renderer concern, not declared in the neutral config.

---

## NormalizedStage object

A `NormalizedStage` is a fully resolved stage — no profile references, no defaults, no
gaps. This is what every renderer receives.

```
NormalizedStage {
  id:           string          // unique within the config
  kind:         StageKind
  provider:     string          // e.g. "openai", "anthropic", "deepseek"
  backend:      string          // e.g. "codex", "claude-code", "generic"
  model:        string | null   // e.g. "gpt-4o"; null = backend default
  skill:        string          // skill id → .agentic/skills/<id>/SKILL.md
  gate:         StageGate
  triggers:     StageTrigger[]
  dependencies: string[]        // ids of stages that must reach PASS before this starts
}
```

See `03-provider-backend-model.md` for how `provider`, `backend`, and `model` relate
and how defaults are resolved.

---

## Stage graph and dependency normalization

After parsing and profile expansion, all stages are placed into a directed acyclic graph
(DAG) where edges represent `dependencies`. The graph is validated for:

1. **Acyclicity** — no circular dependency chains
2. **Reference validity** — every id in any `dependencies` array exists as a stage id
3. **Dependency-closure of routes** — when RoutingPolicy declares a stage subset for a
   route, that subset must include all transitive dependencies of every stage it contains
   (see `05-governance-and-trust.md`)

---

## Dependency semantics — precise rule

> **A dependent stage becomes eligible to start only when all of its declared
> dependencies have reached a terminal state with `conclusion = PASS`.**
>
> If any declared dependency reaches a terminal state with `conclusion = BLOCKED` or
> `conclusion = FAILED`, the dependent stage does **not** start and its own conclusion
> is set to `FAILED` (dependency failure propagation).

This is the V1 rule. There is no conditional dependency ("run even if upstream failed")
in V1. Stages with `dependencies: []` are unconditionally independent — they start
whenever their declared `triggers` fire.

### Example

```
build  (no dependencies)
test   (dependencies: [build])
```

- `build` starts on PR_UPDATED.
- `test` starts only after `build` concludes PASS.
- If `build` concludes FAILED, `test` does not start.

---

## Profile expansion

Profiles are named presets that supply default field values. Expansion rules:

1. A profile reference is replaced by its template fields **before** any other
   normalization.
2. Operator-supplied fields override profile defaults — the operator's config always
   wins.
3. After expansion, every stage must have all required fields; any missing required
   field is a static validation error.
4. Profile expansion is purely additive — it never removes a field the operator declared.

Expansion order:

```
Raw config YAML
    → Profile expansion
    → Operator field override merge
    → backend/model default resolution (see 03-provider-backend-model.md)
    → Dependency normalization
    → NormalizedStage[]
```

The output is a fully concrete `NormalizedStage[]`. This array is what every renderer
receives as part of `RenderContext`.

---

## V1 shipped profiles

Stagr V1 ships three built-in profiles. Operators reference them by id in their config.
Each profile is a named preset; an operator can override any field it sets.

### `minimal`

Intended for documentation-only repositories or small utilities that need only a
lightweight review pass.

Normalized output:
```
stages:
  - id: review
    kind: REVIEW
    provider: openai
    backend: codex
    model: null          // backend default
    skill: review        // .agentic/skills/review/SKILL.md
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: []
```

### `standard`

Intended for application code repositories. Adds a security review stage that runs
independently of the code review.

Normalized output:
```
stages:
  - id: review
    kind: REVIEW
    provider: openai
    backend: codex
    model: null
    skill: review
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: []

  - id: security
    kind: SECURITY
    provider: openai
    backend: codex
    model: null
    skill: security
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: []
```

### `extended`

Intended for repositories that also need automated build and test validation alongside
AI review. Adds `build` and `test` stages; `test` depends on `build`.

Normalized output:
```
stages:
  - id: review
    kind: REVIEW
    provider: openai
    backend: codex
    model: null
    skill: review
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: []

  - id: security
    kind: SECURITY
    provider: openai
    backend: codex
    model: null
    skill: security
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: []

  - id: build
    kind: BUILD
    provider: openai
    backend: codex
    model: null
    skill: build
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: []

  - id: test
    kind: TEST
    provider: openai
    backend: codex
    model: null
    skill: test
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: [build]
```

> **Note:** Profile field values (especially `provider`, `backend`, `model`) are
> documented here as the V1 default resolution. Operators may override any field per
> stage in their config.
