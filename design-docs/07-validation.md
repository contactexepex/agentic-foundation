# Stagr Neutral Core — Validation Checklist

**Status:** Design phase — not yet implemented

---

## Overview

Validation separates into two phases: **static** (config alone, no environment access)
and **environment** (requires network access, credentials, and a configured platform).

---

## CLI commands

| Command | What it checks | Requires environment |
|---|---|---|
| `stagr plan` | Static validation + lists planned artifacts (what would be written) | No |
| `stagr doctor` | Static validation + environment readiness | Yes |
| `stagr apply` | Static validation, then renders and writes artifacts | No (but `doctor` should pass first) |

`stagr plan` and `stagr apply` share the same static validation pass. Any static error
that fails `plan` also fails `apply`.

---

## Static validation

Errors here fail `stagr plan` and prevent `stagr apply` from writing any artifacts.

### V-S01 — Config schema validity

All required fields are present; all field values are recognized enum members or valid
strings; no unrecognized top-level keys.

### V-S02 — Schema version support

The declared `version` is supported by this Stagr CLI. An unsupported version is a hard
error; the CLI must not attempt to render it.

### V-S03 — Stage ID uniqueness

No two stages share the same `id`.

### V-S04 — Dependency graph acyclicity

No cycles exist in the `dependencies` graph. Detection: topological sort; any cycle
causes a static error naming the cycle.

### V-S05 — Dependency reference validity

Every id referenced in any stage's `dependencies` array exists as a stage id in the
config.

### V-S06 — Skill file existence

Each `stage.skill` resolves to an existing `.agentic/skills/<id>/SKILL.md` file.

### V-S07 — BackendRenderer availability

A registered BackendRenderer exists for every `(provider, backend)` pair in the config.

### V-S08 — Platform renderer compatibility

The target PlatformRenderer supports every `InvocationKind` present in the
ExecutionPlans that would be generated. Catches `CI_COMPONENT` incompatibilities with
the target platform.

### V-S09 — Route dependency-closure

When `routing.fast_path.enabled: true`, the stage set declared for each route
(`stages.fast` and `stages.normal`) must be dependency-closed: for every stage S in the
set, all of S's transitive dependencies are also in the set.

### V-S10 — MergePolicy non-empty blocking stages

When `modules.auto_merge: true`, `MergePolicy.blockingStageIds` must be non-empty. A
merge gate with no blocking stages is trivially satisfied and almost certainly a
misconfiguration.

### V-S11 — Routing policy consistency

When `routing.fast_path.enabled: false`, no `match.paths` or `stages` keys are present
(dead configuration).

### V-S12 — Secret alias resolution

All `SecretRef.alias` values declared by the BackendRenderer for each stage are
resolvable: either an explicit mapping exists in provider configuration, or the alias
equals the platform secret name by convention. Static resolution means the alias is
registered; run-time presence is checked by `stagr doctor`.

---

## Environment validation (`stagr doctor`)

Warnings and errors here do not prevent `stagr apply` from running, but they indicate
conditions that will cause run-time failures. All `doctor` checks should pass before
relying on the generated pipeline.

### V-E01 — Required secrets present

Every `SecretRef.envName` in every `ExecutionPlan.requiredSecrets` is configured as a
repository or environment secret on the target platform. Missing secrets produce
`doctor` errors.

### V-E02 — Backend app/integration installed

Each provider's GitHub App, OAuth integration, or equivalent is installed on the
repository and has the permissions that the backend requires (e.g., PR comment write,
review thread read).

### V-E03 — Platform permissions

The repository has the workflow permissions that the generated artifacts require (e.g.,
`pull-requests: read`, `statuses: read`, `contents: read`). Validates against the
minimal `permissions:` blocks that the PlatformRenderer will generate.

### V-E04 — TrustPolicy author roles reachable

The `trustedRoles` configured in `TrustPolicy` includes at least one role that the
repository's expected PR authors hold. A TrustPolicy that excludes all likely authors
will cause every PR to be skipped.

---

## Notes

**V-S13 (NON_BLOCKING dependency warning) has been removed.** `NON_BLOCKING` controls
merge-gate participation, not what conclusion a stage can produce. A `NON_BLOCKING`
stage can produce `conclusion = PASS` and is a perfectly valid dependency for any stage,
including `BLOCKING` ones. The original rule was based on a false premise.

**V-E04 from the previous draft (Codex concurrency constraint) has been removed.**
The claim that the Codex backend errors on concurrent code + security reviews has not
been empirically verified. Until the behavior is confirmed through testing, no
architecture or validation rule based on this assumption should be included.

**Operators are responsible for conformance to reference contracts.** Validation
confirms that the *shipped config* conforms to the Stagr contract. It does not
pre-emptively guard against future operator edits that would break conformance —
that is the same model used by Kubernetes manifests, GitHub Actions workflows, and
every widely-adopted configuration-driven tool.
