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

The kind of work a stage performs. Together with the stage's executor (see "NormalizedStage
object") it determines what handles the stage.

| Value | Semantics |
|---|---|
| `REVIEW` | Code-quality review by a model-backed provider. Completes when the reviewer finishes processing the head commit; findings may be present. Always an `agent` stage. |
| `SECURITY` | Security-focused review. Same completion semantics as REVIEW. Always an `agent` stage. The `standard` profile makes it depend on REVIEW. |
| `BUILD` | Compile/package step. Completes when the build finishes; conclusion is PASS only when the build succeeds. Never an `agent` stage. |
| `TEST` | Automated test run. Completes when tests finish; conclusion is PASS only when all tests pass. Never an `agent` stage. |
| `DEPLOY` | Deployment step. Environment-specific semantics. |
| `CUSTOM` | Operator-defined. With an `agent` executor its semantics come from the referenced skill; with a `commands` or `observed` executor, from those commands or that observed result. |
| `IMPLEMENT` | Agentic implementation step. An AI agent (e.g., Claude Code, Codex) reads the task and produces code changes. Completes when the agent finishes its implementation run. Unlike `REVIEW` and `SECURITY`, findings are not expected — the output is a commit or PR update, not a report. |

### StageGate

Controls whether a stage's conclusion must be PASS before the merge gate passes.

| Value | Semantics |
|---|---|
| `BLOCKING` | The merge gate requires this stage to have reached conclusion=PASS on the current head SHA before the PR can merge. |
| `NON_BLOCKING` | The stage runs and its result is reported, but the merge gate does not wait for it. |

A stage that does not declare a gate is `BLOCKING`, whatever its kind. `REVIEW` and
`SECURITY` stages must be `BLOCKING` (see "Gate-semantics constraint" in
`06-runtime-boundary.md`); `NON_BLOCKING` exists for `commands` and `observed` stages.

`MergePolicy.blockingStageIds` is derived at normalization time as the list of all
stage IDs where `gate == BLOCKING`. It is never re-derived at render time or run time.

### StageTrigger

When a stage's execution is requested.

| Value | Semantics |
|---|---|
| `PR_OPENED` | Fires when a PR transitions to an open, non-draft state. |
| `PR_UPDATED` | Fires on every push to an open, non-draft PR. |
| `MANUAL` | Fires only when explicitly triggered (e.g., a human command). |
| `ISSUE_LABELED` | Fires when a specific label is applied to an issue. Used to trigger agentic implementation from an issue queue (e.g., applying a `codex-engineering` dispatch label). |

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
  gate:         StageGate
  triggers:     StageTrigger[]
  dependencies: string[]        // ids of stages that must reach PASS before this starts
  executor:     AgentExecutor | CommandsExecutor | ObservedExecutor
}

AgentExecutor {                 // an AI backend does the work (review, security, implement)
  provider:     string          // e.g. "openai", "anthropic", "deepseek"
  backend:      string          // e.g. "codex", "claude-code", "generic"
  model:        string | null   // e.g. "gpt-4o"; null = backend default
  skill:        string          // skill id → .agentic/skills/<id>/SKILL.md
}

CommandsExecutor {              // a CI job rendered by Stagr runs the commands
  commands:       string[]      // at least one, run in order
  timeoutMinutes: integer       // 1..360
}

ObservedExecutor {              // the team's own CI or a service does the work
  check:        string          // name of the result to read
  producer:     string          // identity allowed to author it
}
```

See `09-check-stages.md` for the executor rules and the check-stage result model.

`NormalizedStage` does **not** carry an `enabled` field. Disabled stages are removed
during preprocessing — before this object is produced. See "Stage activation and the
`enabled` field" below.

See `03-provider-backend-model.md` for how an `AgentExecutor`'s `provider`, `backend`,
and `model` relate and how defaults are resolved. A `CommandsExecutor` or
`ObservedExecutor` has none of them.

---

## Stage activation and the `enabled` field

The config-level `enabled` field controls whether a stage participates in normalization.
It is a pre-normalization annotation, not a `NormalizedStage` field.

```yaml
# Example: stage defined but inactive
- id: implement-codex
  type: implement
  provider: openai
  enabled: false          # optional; default is true
  triggers: [issue_labeled]
```

**Preprocessing rule:** Stagr removes all stages with `enabled: false` from the active
stage set after profile expansion and operator override merging, but before backend/model
resolution, dependency graph construction, policy derivation, and `NormalizedStage[]`
production. A disabled stage does not appear in
`NormalizedStage[]`, is not included in the dependency graph, does not contribute to
`MergePolicy.blockingStageIds`, is not subject to routing-closure validation, and is
not rendered into any artifact.

**Schema validation still applies** to a disabled stage's declared fields. A malformed
disabled stage (e.g., an invalid `type` or unrecognized field) is a static validation
error regardless of `enabled: false`. The operator receives the same schema feedback
they would receive if the stage were active.

**Dependency rule:** An active stage must not declare a dependency on a disabled stage
id. If stage B has `depends_on: [A]` and stage A has `enabled: false`, Stagr reports
a schema error (V-S02 reference validity) at render time. The operator must either
re-enable A, remove B's dependency on A, or also disable B.

**Rationale:** Defining `enabled: false` as a pre-normalization exclusion (rather than
a renderer hint) ensures that the `NormalizedStage[]` array is always the complete,
authoritative list of active stages. No renderer needs to check `enabled`; the field
has been fully consumed before any renderer sees the stage list.

---

## Stage graph and dependency normalization

After parsing, profile expansion, and disabled-stage removal, all active stages are
placed into a directed acyclic graph (DAG) where edges represent `dependencies`. The
graph is validated for:

1. **Acyclicity** — no circular dependency chains
2. **Reference validity** — every id in any `dependencies` array exists as an active
   stage id (disabled stages do not satisfy this check — see "Stage activation" above)
3. **Dependency-closure of routes** — when RoutingPolicy declares a stage subset for a
   route, that subset must include all transitive dependencies of every stage it contains
   (see `05-governance-and-trust.md`)

---

## Dependency semantics — precise rule

> **A dependent stage becomes eligible to start only when all of its declared
> dependencies have reached `conclusion = PASS`.**

**While any dependency is anything other than `COMPLETED` + `PASS`** (no result yet,
`RUNNING`, `BLOCKED`, `COMPLETED` + `FAILED`, or state `FAILED`): The dependent stage
remains `PENDING`. It does not start, and its own conclusion is not set. A dependency's
result is mutable — it may turn `PASS` when findings are resolved (`BLOCKED`) or when a
later attempt or a new push succeeds (`FAILED`), so the dependent stage re-evaluates
eligibility on each event that updates an upstream signal. An upstream failure is never
propagated: a dependent that failed for good because its upstream failed once would stay
failed after the upstream is fixed.

There is no conditional dependency ("run even if upstream failed") in V1. Stages with
`dependencies: []` are unconditionally independent — they start whenever their declared
`triggers` fire.

### Example

```
build  (no dependencies)
test   (dependencies: [build])
```

- `build` starts on PR_UPDATED.
- `test` starts only after `build` concludes PASS.
- If `build` is `COMPLETED/BLOCKED` (e.g., a lint finding), `test` stays PENDING and
  re-evaluates when `build` reconciles.
- If `build` fails (a compile error, or an infrastructure error), `test` does not start
  and is not marked failed. It starts when `build` later concludes PASS.

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
    → enabled:false filtering (disabled-stage removal)
    → backend/model default resolution (see 03-provider-backend-model.md)
    → Dependency normalization
    → NormalizedStage[]
```

The output is a fully concrete `NormalizedStage[]`. This array is what every renderer
receives as part of `RenderContext`.

---

## V1 shipped profiles

Stagr V1 ships two built-in profiles. Operators reference them by id in their config.
Each profile is a named preset; an operator can override any field it sets.

### `minimal`

Intended for documentation-only repositories or small utilities that need only a
lightweight review pass.

Normalized output:
```
stages:
  - id: review
    kind: REVIEW
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: []
    executor: AgentExecutor { provider: openai, backend: codex, model: null, skill: code-review }
```

### `standard`

Intended for application code repositories. It is the baseline of `09-check-stages.md`:
build, unit tests, code review, security review. The commands of `build` and `unit-test`
come from the top-level `build:` block.

Normalized output:
```
stages:
  - id: build
    kind: BUILD
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: []
    executor: CommandsExecutor { commands: <from build:>, timeoutMinutes: 30 }

  - id: unit-test
    kind: TEST
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: [build]
    executor: CommandsExecutor { commands: <from build:>, timeoutMinutes: 30 }

  - id: review
    kind: REVIEW
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: [build]
    executor: AgentExecutor { provider: openai, backend: codex, model: null, skill: code-review }

  - id: security
    kind: SECURITY
    gate: BLOCKING
    triggers: [PR_OPENED, PR_UPDATED]
    dependencies: [review]      // the two reviews run in sequence (09-check-stages.md, section 10)
    executor: AgentExecutor { provider: openai, backend: codex, model: null, skill: security-review }
```

### `custom`

The identity profile — no expansion. A stage that declares `profile: custom` (or a
config that declares `profile: custom` at the top level) receives no default field
injection from any built-in preset. Every field the stage requires must be declared
explicitly by the operator. This is the correct choice for operators who need stage types
or trigger patterns not covered by `minimal` or `standard` (e.g., `IMPLEMENT` stages
with `ISSUE_LABELED` triggers).

> **Note:** Profile field values (especially `provider`, `backend`, `model`) are
> documented here as the V1 default resolution. Operators may override any field per
> stage in their config.
