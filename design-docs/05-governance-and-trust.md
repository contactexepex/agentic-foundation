# Stagr Neutral Core — Governance and Trust

**Status:** Target design. What is built today is in
[ARCHITECTURE.md, section 8](../docs/ARCHITECTURE.md#8-status--roadmap).

---

## Overview

This document defines the three policy objects that govern pipeline eligibility,
routing, and the gate result: **TrustPolicy**, **RoutingPolicy**, and **MergePolicy**.
All three are derived at normalization time and passed to the PlatformRenderer in
`RenderContext`. None of them is re-derived at run time. The rules engine applies them
(`06-runtime-boundary.md`).

---

## TrustPolicy

`TrustPolicy` declares who and what Stagr-generated automation may act on behalf of.
It is security-critical: Stagr generates workflows that post comments using
trusted-user credentials and run in privileged CI contexts. The TrustPolicy ensures these
privileges are never exercised on behalf of untrusted or fork-sourced work.

```
TrustPolicy {
  trustedRoles: AuthorRole[]   // e.g. [OWNER, MEMBER, COLLABORATOR]
  forkPolicy:   ForkPolicy     // how changes from forks are handled (see ForkPolicy below)
}
```

> **Identity roles are redesigned in Plan B.** `AuthorRole` and `trustedRoles` stay as they are
> here until Plan B replaces them with neutral identity roles and an org-configurable mapping
> (#265, section 2, decision 10).

### ForkPolicy

| Value | Meaning |
|---|---|
| `DENY` | Changes from forks never drive any stage execution. The stage execution artifact exits immediately when the change comes from a fork. This is the secure default. |
| `ALLOW_UNPRIVILEGED` | Changes from forks may drive stages that require no elevated platform capabilities (no `requiredSecrets`, no write-capable platform tokens). Privileged stages still refuse them. |

> **`privilegedStages` is derived, not operator-declared.** A stage is privileged if it
> requires any elevated platform capability, which includes: `ExecutionPlan.requiredSecrets`
> is non-empty, OR the stage execution artifact requires a write-capable platform token
> (including a token that can request an identity token from the platform). These are
> determined by the BackendRenderer and PlatformRenderer at render time. Stagr derives the
> privileged set automatically; the operator does not need to, and must not, duplicate this
> in the config. Operator duplication would create a second source of truth that drifts from
> the actual capability requirements.

### AuthorRole

| Value | Meaning |
|---|---|
| `OWNER` | Repository owner |
| `MEMBER` | Organization member |
| `COLLABORATOR` | Explicit collaborator |
| `CONTRIBUTOR` | First-time or external contributor (NOT trusted by default) |

How each platform reports these roles is in the platform mapping (`08-github-codex-mapping.md`
for GitHub).

### TrustPolicy rules

1. **Changes from forks are controlled by `forkPolicy`.** When `forkPolicy: DENY` (the
   default), a change whose source is a forked repository must not trigger any stage execution
   artifact. When `forkPolicy: ALLOW_UNPRIVILEGED`, it may trigger unprivileged stages only;
   privileged stages must still refuse it.

2. **Untrusted authors never drive automation.** An author whose role is not in
   `trustedRoles` must not trigger any privileged stage.

3. **Privileged jobs are identified automatically and never run change content.** A stage is
   privileged when its `ExecutionPlan.requiredSecrets` is non-empty, or when the stage execution
   artifact requires a write-capable platform token. A PlatformRenderer must render privileged
   jobs from the trusted base's definition, never from the change, and must never check out or
   execute change content inside a privileged job. How the GitHub renderer meets this is in
   `08-github-codex-mapping.md`.

---

## RoutingPolicy

`RoutingPolicy` declares how changed file paths are classified into route classes, and
which stages apply to each route.

```
RoutingPolicy {
  fastPath: FastPathPolicy | null   // null when fast_path.enabled: false
}

FastPathPolicy {
  match: PathMatchSpec
  stages: RouteStageMap
}

PathMatchSpec {
  paths: string[]   // glob patterns; a change set matching ALL paths = FAST route
}

RouteStageMap {
  fast:   string[]   // stage ids that run on the FAST route
  normal: string[]   // stage ids that run on the NORMAL route
}
```

### Route classification

At run time, the routing artifact classifies a change's revision into one of two routes:

| Route | Meaning |
|---|---|
| `FAST` | All changed files match the `fastPath.match.paths` patterns. The `fast` stage subset applies. |
| `NORMAL` | One or more changed files do not match the patterns (or fast_path is disabled). The `normal` stage subset applies (all eligible stages). |

### V1 routing constraint: deterministic classification only

In V1, routing is **deterministic** — classification is based solely on which file
paths changed, using the declared glob patterns. AI-driven or probabilistic
classification is not permitted in V1. This ensures routing is reproducible, auditable,
and free of external API dependencies.

### Dependency-closure validation

The stage set declared for each route must be **dependency-closed**: if a stage S is
in the route's set and S has a declared dependency D, then D must also be in the set.
A route that contains `integration-test` while omitting `build` (on which
`integration-test` depends) is invalid.

Stagr must enforce this at normalization time as a static validation error (V-S09 in
`07-validation.md`).

### RouteClassification runtime signal

At run time, the routing artifact emits a `RouteClassification` signal:

```
RouteClassification {
  route:    FAST | NORMAL
  revision: string
}
```

Revision binding is mandatory. A `RouteClassification` without a `revision` cannot be
safely consumed because a stale FAST classification for a prior revision could cause the
governance artifact to skip blocking stages for a new revision.

**Provenance requirement.** The governance artifact must only consume a
`RouteClassification` that the Stagr-generated routing artifact published on a result carrier
bound to the revision and written by the publisher identity, the same carrier as a
`StageResultSignal` (`06-runtime-boundary.md`, "Signal emission"). The governance artifact must
verify the publisher identity before treating the route classification as authoritative.

---

## MergePolicy

`MergePolicy` declares what the gate result requires. It is derived entirely at
normalization time from the config and the TrustPolicy. It is never re-derived at run
time.

```
MergePolicy {
  blockingStageIds:     string[]                 // derived: all stages where gate == BLOCKING
  discussionPolicy:     DiscussionPolicy | null  // null = no discussion requirement
  requireRevisionBound: boolean                  // true = every StageResultSignal must match
                                                 // the current revision
}
```

### DiscussionPolicy

`DiscussionPolicy` is the neutral representation of the "zero unresolved discussions"
requirement. It is neutral — it does not name platform-specific objects; the GitHub mapping is in
`08-github-codex-mapping.md`.

```
DiscussionPolicy {
  requireResolved: boolean   // true = all open review discussions must be resolved
                             // before the gate result passes
}
```

When `discussionPolicy` is null, the gate does not check discussion state.

### The gate result

The governance artifact publishes one gate result, and the platform's own merge mechanism
merges; Stagr never merges (#265, section 2, decision 4). The conditions of the gate result are
in `06-runtime-boundary.md`, "Gate evaluation".

An external check (for example SonarCloud) is an observed stage (`09-check-stages.md`), so it
is a stage like any other: it is in `blockingStageIds` when blocking, and an absent result
keeps the gate from passing.

### MergePolicy derivation

`blockingStageIds` is derived at normalization time as:

```
blockingStageIds = [stage.id for stage in normalizedStages if stage.gate == BLOCKING]
```

This list is fixed at render time. The governance artifact receives it as a constant;
it never evaluates stage gate values at run time.
