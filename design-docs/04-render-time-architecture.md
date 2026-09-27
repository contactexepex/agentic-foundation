# Stagr Neutral Core — Render-Time Architecture

**Status:** Design phase — not yet implemented

---

## Overview

Render time is when Stagr translates the neutral config into platform-native artifacts.
It happens once per config change, triggered by `stagr apply`. After rendering, Stagr
has no further involvement; the generated artifacts run entirely inside the target
platform.

---

## Render pipeline

The pipeline has two independent paths:

### Path 1 — Per-stage execution artifacts

For each `NormalizedStage` in `RenderContext.stages`:

```
NormalizedStage
      │
      ▼
BackendRenderer(provider, backend)
      │  produces
      ▼
ExecutionPlan { invocation, requiredSecrets, evidence }
      │
      ▼
PlatformRenderer
      │  writes
      ▼
Stage execution artifact (e.g., one GitHub Actions workflow file per stage)
```

### Path 2 — Pipeline governance artifacts

Once per config, using `RenderContext.routingPolicy` and `RenderContext.mergePolicy`:

```
RoutingPolicy + MergePolicy + StageResultSpec[]
      │
      ▼
PlatformRenderer
      │  writes
      ▼
Routing artifact + Governance/merge artifact
```

**Separation rule:** Path 1 renderers never read routing or merge policy. Path 2
renderers never read stage `ExecutionPlan` objects. However, Path 2 **does** receive
a `StageResultSpec[]` — a summary of how each blocking stage's completion will be
signalled at run time. See [StageResultSignal and StageResultSpec](#stageresultsignal-and-stageresultspec) below.

---

## RenderContext

Everything a renderer receives. Passed by the Stagr CLI; never derived by the renderer.

```
RenderContext {
  stages:           NormalizedStage[]
  stageResultSpecs: StageResultSpec[]      // one per blocking stage; for Path 2
  routingPolicy:    RoutingPolicy
  mergePolicy:      MergePolicy
  trustPolicy:      TrustPolicy
  platform:         string                 // e.g. "github", "gitlab", "bitbucket"
  configVersion:    string
}
```

---

## Full object model

### ExecutionPlan

The intermediate representation between BackendRenderer and PlatformRenderer. Opaque to
the neutral contract beyond this structure.

```
ExecutionPlan {
  stageId:         string
  invocation:      Invocation
  requiredSecrets: SecretRef[]
  evidence:        EvidenceSpec[]
}
```

### Invocation

How the backend is asked to execute the stage. Backend-defined; interpreted by the
PlatformRenderer for each supported `InvocationKind`.

```
Invocation {
  kind:   InvocationKind
  params: Record<string, unknown>   // backend-defined; platform-renderer–interpreted
}
```

### InvocationKind

| Value | Semantics | Platform notes |
|---|---|---|
| `PR_COMMENT` | Post a comment on the PR to trigger the backend | GitHub: `gh pr comment` via trusted-user PAT |
| `API_CALL` | Call the provider's API directly from a CI step | Backend-specific HTTP call |
| `WORKFLOW_DISPATCH` | Trigger a CI workflow by name/id | GitHub: `workflow_dispatch` event |
| `CI_COMPONENT` | Insert a native CI component (Action, GitLab component, etc.) | **Platform-dependent by design.** Validation catches incompatibilities at render time. |

### StageResultSpec

A `StageResultSpec` is the render-time declaration of how a stage will signal its
result at run time. Path 2 uses this to generate the governance artifact without
reading raw `EvidenceSpec` details.

```
StageResultSpec {
  stageId:        string
  signalKind:     StageResultSignalKind   // how the signal is published at run time
  signalSelector: string                  // platform-specific locator for the signal
}
```

`StageResultSignalKind` values: `COMMIT_STATUS`, `CHECK_RUN`, `WORKFLOW_OUTPUT`

The BackendRenderer produces the `EvidenceSpec[]` (how to detect raw completion) and
the `StageResultSpec` (how the governance artifact finds the normalized result). The
PlatformRenderer for a stage execution artifact writes the observation logic that
converts raw evidence into a `StageResultSignal` (see `06-runtime-boundary.md`).

### EvidenceSpec

How stage completion is detected at run time. Backend-supplied; consumed by the
PlatformRenderer writing the stage execution artifact. Uses semantic vocabulary —
not platform-object names.

```
EvidenceSpec {
  kind:             EvidenceKind
  selector:         string                    // backend-defined, opaque to neutral contract
  correlation:      CorrelationSpec
  successCondition: EvidenceSuccessCondition
}
```

See `06-runtime-boundary.md` for `EvidenceKind`, `CorrelationSpec`, and
`EvidenceSuccessCondition` definitions.

---

## StageResultSignal and StageResultSpec

This is the critical connector between stage execution artifacts (Path 1) and the
governance artifact (Path 2).

### The problem without it

Path 1 generates stage execution artifacts that detect raw backend evidence (e.g., a
Codex comment row containing "Completed"). Path 2 generates a governance artifact that
must decide merge eligibility. Without a normalized signal between them, the governance
artifact must understand every possible backend's raw output format — breaking
provider-neutrality.

### The solution: StageResultSignal

At run time, each stage execution artifact **emits a `StageResultSignal`** to a
well-known platform location (e.g., a commit status or check run output). The
governance artifact reads these signals, not raw evidence.

```
StageResultSignal {
  stageId:    string
  headSha:    string
  state:      StageResultState
  conclusion: StageResultConclusion
}
```

### StageResultState

| Value | Meaning |
|---|---|
| `PENDING` | Stage has not started yet |
| `RUNNING` | Stage invocation is in flight |
| `COMPLETED` | Stage finished processing (regardless of findings) |
| `FAILED` | Stage could not finish (infrastructure failure, timeout) |

### StageResultConclusion

| Value | Meaning |
|---|---|
| `PASS` | Stage completed and the result satisfies the gate (no blocking findings) |
| `BLOCKED` | Stage completed but findings or conditions prevent a merge-gate pass. For review stages: review finished with unaddressed findings. |
| `FAILED` | Stage did not finish successfully (infrastructure failure, dependency failed) |
| `UNKNOWN` | Signal received but conclusion cannot be determined (malformed signal, version mismatch) |

### Why COMPLETED ≠ PASS for review stages

A code review that produces 3 serious findings is `COMPLETED` (the reviewer finished
processing) but `BLOCKED` (the findings prevent merge). The gate requires
`conclusion = PASS`, not `state = COMPLETED`. This separation prevents a completed
review with outstanding findings from satisfying a blocking gate.

### Signal flow

```
Stage execution artifact (runtime)
    ├── Detects raw backend evidence (via EvidenceSpec)
    ├── Determines state and conclusion
    └── Emits StageResultSignal
            │
            ▼ (platform-native signal: commit status / check run)
Governance artifact (runtime)
    ├── Reads StageResultSignal for each blockingStageId
    ├── Checks: state ∈ {COMPLETED} AND conclusion = PASS for current headSha
    └── Reports merge eligibility
```

---

## Three artifact classes

| Class | Produced by | Examples (GitHub) | Responsibility |
|---|---|---|---|
| **Stage execution artifact** | Path 1, one per stage | One workflow file per stage | Trigger on declared StageTriggers; invoke the backend; detect evidence; emit StageResultSignal |
| **Routing artifact** | Path 2 | `fast-ai-code-review.yml` | Classify changed files; emit `RouteClassification` signal |
| **Governance / merge artifact** | Path 2 | `auto-merge-foundation-prs.yml` | Read `StageResultSignal` for each blocking stage + `RouteClassification`; enforce `MergePolicy`; merge when eligible |

---

## Four authority rules

1. **Normalized stage graph** owns execution semantics: what runs, when, and with what
   dependency ordering.
2. **RoutingPolicy** owns stage applicability: which stages run on FAST vs NORMAL routes.
3. **EvidenceSpec** owns raw completion detection: what backend output counts as the
   stage having processed a given head commit.
4. **MergePolicy** owns merge eligibility: which stages must have `conclusion = PASS`
   for the head to be mergeable.

No renderer may override these four authorities. Any conflict is a renderer bug.

---

## Renderer invariants

### R1 — No invented dependencies

A renderer must not produce an artifact that enforces a dependency between two stages
unless that dependency is declared in `NormalizedStage.dependencies`. Concurrency
management between stages is never a renderer's prerogative to add.

### R2 — Evidence does not gate invocation

EvidenceSpec describes how to prove a stage result. It must never define whether the
stage should have run. Stage `triggers` determine invocation; `EvidenceSpec` determines
completion detection only.

### R3 — MergePolicy is read-only at run time

The governance artifact contains `MergePolicy.blockingStageIds` as a fixed list
rendered into it at render time. No run-time event may alter this list.

### R4 — StageResultSignals are emitted, never assumed

A governance artifact never makes assumptions about a stage's result based on indirect
evidence (e.g., "if the review comment exists, the review must have passed"). It reads
only normalized `StageResultSignal` values emitted by stage execution artifacts.
