# Stagr Neutral Core — Governance and Trust

**Status:** Design phase — not yet implemented

---

## Overview

This document defines the three policy objects that govern pipeline eligibility,
routing, and merge decisions: **TrustPolicy**, **RoutingPolicy**, and **MergePolicy**.
All three are derived at normalization time and passed to the PlatformRenderer in
`RenderContext`. None of them is re-derived at run time.

---

## TrustPolicy

`TrustPolicy` declares who and what Stagr-generated automation may act on behalf of.
It is security-critical: Stagr generates workflows that post comments using
trusted-user credentials and run in privileged CI contexts (e.g., GitHub's
`pull_request_target`). The TrustPolicy ensures these privileges are never exercised
on behalf of untrusted or fork-sourced work.

```
TrustPolicy {
  trustedRoles:    AuthorRole[]   // e.g. [OWNER, MEMBER, COLLABORATOR]
  forkPolicy:      ForkPolicy     // how fork PRs are handled (see ForkPolicy below)
  humanMergeLabel: string         // label name that forces the human-gated lane
                                  // (e.g. "human-merge"); never auto-merged when present
}
```

### ForkPolicy

| Value | Meaning |
|---|---|
| `DENY` | Fork PRs never drive any stage execution. The stage execution artifact exits immediately when the PR head originates from a fork. This is the secure default. |
| `ALLOW_UNPRIVILEGED` | Fork PRs may drive stages that require no elevated platform capabilities (no `requiredSecrets`, no write-capable platform tokens). Privileged stages still refuse fork PRs. |

> **`privilegedStages` is derived, not operator-declared.** A stage is privileged if it
> requires any elevated platform capability, which includes: `ExecutionPlan.requiredSecrets`
> is non-empty, OR the stage execution artifact requires a write-capable platform token
> (e.g., `GITHUB_TOKEN` with write scopes, or `id-token: write` for OIDC). These are
> determined by the BackendRenderer and PlatformRenderer at render time. Stagr derives the
> privileged set automatically; the operator does not need to, and must not, duplicate this
> in the config. Operator duplication would create a second source of truth that drifts from
> the actual capability requirements.

### AuthorRole

| Value | Meaning (GitHub mapping) |
|---|---|
| `OWNER` | Repository owner |
| `MEMBER` | Organization member |
| `COLLABORATOR` | Explicit collaborator |
| `CONTRIBUTOR` | First-time or external contributor (NOT trusted by default) |

### TrustPolicy rules

1. **Fork PRs are controlled by `forkPolicy`.** When `forkPolicy: DENY` (the default),
   any PR where the head branch originates from a forked repository must not trigger any
   stage execution artifact. When `forkPolicy: ALLOW_UNPRIVILEGED`, fork PRs may trigger
   unprivileged stages only; privileged stages must still refuse fork PRs.

2. **Untrusted authors never drive automation.** A PR author whose `author_association`
   is not in `trustedRoles` must not trigger any privileged stage.

3. **Privileged workflows are identified automatically.** A stage is privileged when its
   `ExecutionPlan.requiredSecrets` is non-empty, or when the stage execution artifact
   requires a write-capable platform token (e.g., `GITHUB_TOKEN` write scopes, OIDC
   `id-token: write`). A PlatformRenderer must verify that privileged workflows use
   `pull_request_target` (not `pull_request`) and never check out or execute PR head
   content inside a privileged job.

4. **The human-merge label is a hard stop.** When the label named in `humanMergeLabel`
   is present on a PR, the governance artifact must refuse to auto-merge regardless of
   all other conditions. This is not configurable per-PR at run time; it is rendered
   into the governance artifact as a fixed hard stop.

### GitHub `pull_request_target` safety

GitHub's `pull_request_target` event gives a workflow access to repository secrets and
write-capable tokens, even when triggered by a fork PR. This is a known
repository-compromise vector. The PlatformRenderer **must** enforce the following when
generating workflows that use `pull_request_target` with secrets:

- The workflow must verify `author_association` is in `trustedRoles` before using any
  secret.
- The workflow must verify the PR head is from the same repository (`head.repo.full_name
  == GITHUB_REPOSITORY`) before proceeding.
- The workflow must never check out, execute, or evaluate PR head content inside a job
  that holds secrets.
- All of the above checks must be enforced in-script (a `pull_request_target` job-level
  `if:` cannot safely guard these conditions because the PR fields are not available for
  all trigger events).

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

At run time, the routing artifact classifies a PR head commit into one of two routes:

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
  route:   FAST | NORMAL
  headSha: string
}
```

Head SHA binding is mandatory. A `RouteClassification` without a `headSha` cannot be
safely consumed because a stale FAST classification for a prior commit could cause the
governance artifact to skip blocking stages for a new commit.

**Provenance requirement.** The governance artifact must only consume a
`RouteClassification` that was published by the Stagr-generated routing artifact using an
authenticated platform identity. On GitHub, this means the routing artifact must publish
the signal as a **Check Run** (which carries the authenticated GitHub App identity of the
publisher) rather than a commit status (which any `statuses: write` actor can forge). The
governance artifact must verify the Check Run's App identity matches the expected routing
artifact identity before treating the route classification as authoritative.

---

## MergePolicy

`MergePolicy` declares merge eligibility requirements. It is derived entirely at
normalization time from the config and the TrustPolicy. It is never re-derived at run
time.

```
MergePolicy {
  mode:             MergeMode
  blockingStageIds: string[]              // derived: all stages where gate == BLOCKING
  discussionPolicy: DiscussionPolicy | null  // null = no discussion requirement
  requireHeadBound: boolean               // true = all StageResultSignals must match current headSha
}
```

### DiscussionPolicy

`DiscussionPolicy` is the neutral representation of the "zero unresolved discussions"
requirement. It is neutral — it does not name GitHub-specific objects.

```
DiscussionPolicy {
  requireResolved: boolean   // true = all open review discussions must be resolved
                             // before the merge gate passes
}
```

Platform mappings:
- **GitHub**: "unresolved discussions" = unresolved review threads on the PR
- **GitLab**: "unresolved discussions" = unresolved MR discussion threads

When `discussionPolicy` is null, the merge gate does not check discussion state.

### MergeMode

| Value | Meaning |
|---|---|
| `AUTO` | Foundation lane: the governance artifact merges automatically when all conditions are met. No human approval required. |
| `MANUAL` | Human-gated lane: the governance artifact enforces all conditions but does not merge. A human must merge. |

### Two merge lanes

**Foundation lane (`mode: AUTO`):** For PRs that build or maintain the toolkit itself.
Merges automatically once all of the following are true:
- PR is open, non-draft, same-repo, targets the default branch
- Author association is in `TrustPolicy.trustedRoles`
- `TrustPolicy.humanMergeLabel` is NOT present on the PR
- No merge conflict
- All CI checks and commit statuses for **blocking stages** are green; `NON_BLOCKING`
  stage statuses are informational and do not hold the gate
- `StageResultSignal` for every stage in `RequiredStageIds` shows `conclusion = PASS`
  for the current head SHA, where:
  `RequiredStageIds = ApplicableStages(RouteClassification.route) ∩ blockingStageIds`
- `discussionPolicy` is satisfied: if `discussionPolicy.requireResolved` is true, zero
  open review discussions remain (checked via platform API — separate from `StageResultSignal`)
- `RouteClassification.headSha` matches the current head SHA

**Human-gated lane (`mode: MANUAL`):** Any PR that carries `TrustPolicy.humanMergeLabel`
is automatically placed in the human-gated lane, regardless of `mode`. This is a hard
stop: the governance artifact enforces all conditions but does not auto-merge. A human
must perform the merge.

> When in doubt, apply the human-merge label. The foundation lane is an optimization
> for well-understood, provably-safe merges; anything that requires human judgment
> must carry the label.

### External gates (V1)

When `modules.sonar: true`, the governance artifact includes SonarCloud as an **observed
external gate** alongside the Stagr-rendered blocking stages.

```
ExternalGate (V1) {
  checkRunName:      "sonarqubecloud"      // the check run name the governance artifact looks for
  requiredPresence:  when_present          // V1 fixed policy: check is required ONLY IF present
  requiredConclusion: success
}
```

**V1 semantics:**

- When the `sonarqubecloud` check run is present on the current head SHA and its
  conclusion is not `success`, the merge gate does not pass.
- When the `sonarqubecloud` check run is absent from the current head SHA, the gate
  tolerates the absence — it does not block the merge. This is fail-open behavior,
  appropriate for V1 where external App analysis may not yet be reporting on all
  repositories.
- The governance artifact does not verify the publisher identity (App ID) of the
  SonarCloud check run in V1. Provenance verification for external check runs is V2 scope.

**V2 scope (deferred):** Full `ExternalGateSpec { id, selector, requiredPresence, acceptedConclusions, provenance }[]` modeling, configurable per-gate presence requirements, and publisher identity verification are out of V1 scope.

The complete V1 merge gate condition list (condition 10) becomes:

> 10. For each external gate in `modules` with value `true`: if the gate's check run is
>     present on the current head SHA, it must be in its required terminal conclusion.
>     Absent check runs are tolerated in V1.

### MergePolicy derivation

`blockingStageIds` is derived at normalization time as:

```
blockingStageIds = [stage.id for stage in normalizedStages if stage.gate == BLOCKING]
```

This list is fixed at render time. The governance artifact receives it as a constant;
it never evaluates stage gate values at run time.

### Merge gate conditions (complete list)

The governance artifact passes if and only if all of the following hold:

1. PR is open, non-draft, same-repo, targeting the default branch
2. PR author association ∈ `TrustPolicy.trustedRoles`
3. `TrustPolicy.humanMergeLabel` is NOT present
4. No merge conflict
5. Every commit status and check run for **BLOCKING stages** is in a green (passing)
   terminal state. `NON_BLOCKING` stage statuses are reported but do not hold the gate.
6. Routing status (`RouteClassification`) is published and terminal for the current `headSha`
7. For every `stageId` in `RequiredStageIds`: a `StageResultSignal` with
   `headSha = currentHead` and `conclusion = PASS` exists, where:
   `RequiredStageIds = ApplicableStages(RouteClassification.route) ∩ MergePolicy.blockingStageIds`
   Stages not applicable to the current route are excluded — their absence is not a blocker.
8. `discussionPolicy`: if `discussionPolicy` is non-null and `requireResolved` is true,
   zero open review discussions remain (checked via platform discussion API — a separate
   governance condition not derived from `StageResultSignal`)
9. External gates: for each `modules.<gate>: true`, if the gate's check run is present on
   the current head SHA it must be in the required passing terminal state; absent check
   runs are tolerated in V1 (fail-open)
10. `mode = AUTO` (if `MANUAL`, stop here and require human merge)
