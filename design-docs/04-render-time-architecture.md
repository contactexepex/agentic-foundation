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

The pipeline runs in two ordered phases. Phase 1 must complete for all stages before
Phase 2 begins, because Phase 2 consumes outputs produced by Phase 1.

### Phase 1 — Per-stage: BackendRenderer → PlatformRenderer

For each `NormalizedStage` in `RenderContext.stages`:

```
NormalizedStage
      │
      ▼
BackendRenderer(provider, backend)
      │  produces
      ▼
ExecutionPlan { stageId, invocation, requiredSecrets, evidence, gateDisposition }
      │
      ▼
PlatformRenderer
      │  produces
      ├── Stage execution artifact (e.g., one GitHub Actions workflow file per stage)
      └── StageResultSpec  (how this stage signals its result at run time)
```

Each `(ExecutionPlan, NormalizedStage)` pair is processed independently. The
PlatformRenderer writes the stage execution artifact **and** produces a `StageResultSpec`
describing the platform-native signal location where the artifact will publish
`StageResultSignal` values.

### Phase 2 — Pipeline: governance artifacts from collected StageResultSpecs

After all stages in Phase 1 are processed, the collected `StageResultSpec[]` are
available. Phase 2 uses them along with the pipeline policies:

```
RoutingPolicy + MergePolicy + TrustPolicy + StageResultSpec[]
      │
      ▼
PlatformRenderer
      │  writes
      ▼
Routing artifact + Governance/merge artifact
```

**Why two phases?** The governance artifact must know **where** each blocking stage will
publish its `StageResultSignal` at run time. This is determined by the PlatformRenderer
during Phase 1 (not by the BackendRenderer and not from `RenderContext` inputs). Phase 2
therefore cannot begin until all Phase 1 `StageResultSpec` outputs are collected.

**Separation rule:** Phase 1 renderers never read routing or merge policy. Phase 2
renderers never read stage `ExecutionPlan` objects directly — they receive only the
`StageResultSpec[]` summary produced by Phase 1.

---

## RenderContext

Everything a renderer receives as **input**. Passed by the Stagr CLI; never derived by
the renderer. Note: `StageResultSpec[]` is **not** an input — it is produced by Phase 1
and collected by the CLI before Phase 2 begins.

```
RenderContext {
  stages:        NormalizedStage[]
  routingPolicy: RoutingPolicy
  mergePolicy:   MergePolicy
  trustPolicy:   TrustPolicy
  platform:      string                 // e.g. "github", "gitlab", "bitbucket"
  configVersion: string
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
  gateDisposition: GateDispositionSpec   // how to determine PASS vs BLOCKED at run time
}
```

`gateDisposition` is required. It separates "when is the backend done?" (answered by
`evidence`) from "given it is done, is the result PASS or BLOCKED?" (answered by
`gateDisposition`). See `06-runtime-boundary.md` for `GateDispositionSpec` definitions.

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
  provenance:     StageResultProvenance   // expected publisher identity for governance verification
}

StageResultProvenance {
  publisherIdentity: string   // platform-specific identity of the expected signal publisher
                              // (e.g., GitHub App installation ID, workflow file path)
}
```

`StageResultSignalKind` values on GitHub V1: `CHECK_RUN` (required — authenticated App
identity), `WORKFLOW_OUTPUT`. `COMMIT_STATUS` is available as a fallback only for
platforms where Check Runs do not exist; on GitHub V1 it must not be used for
`StageResultSignal` because it is forgeable by any `statuses: write` actor.

`provenance.publisherIdentity` is used by the governance artifact to verify the signal
came from the expected publisher before trusting its conclusion. On GitHub, this is the
GitHub App installation ID or a stable workflow identity that created the Check Run. The
governance artifact must reject any signal whose publisher identity does not match the
rendered `provenance` value.

**How `signalKind == CHECK_RUN` flows to platform capabilities.** When the
PlatformRenderer selects `CHECK_RUN` as `signalKind`, it must:

1. Include `checks: write` in the generated stage execution artifact's `permissions:`
   block (GitHub V1). This is a PlatformRenderer implementation responsibility — it is
   not declared as a field in `ExecutionPlan` because `checks: write` is a GitHub-specific
   permission name that belongs in the PlatformRenderer, not in the neutral intermediate
   representation produced by the BackendRenderer.
2. Do the same for the routing artifact, which also emits an authenticated Check Run
   (`RouteClassification`).

`stagr doctor` V-E03 validates that the repository has the permissions these generated
`permissions:` blocks require. V-E02 validates that the backend App/integration is
installed with the capabilities to create those Check Runs. These two doctor checks are
the verification layer; `ExecutionPlan` does not duplicate them as data model fields.

The BackendRenderer produces the `EvidenceSpec[]` (how to detect raw completion).
The PlatformRenderer for a stage execution artifact uses those `EvidenceSpec` entries to
observe the backend's raw output. The PlatformRenderer **also produces the
`StageResultSpec`** — declaring the platform-native signal location, kind, and expected
publisher identity where it will publish results. Signal locations are platform
primitives; they are determined by the PlatformRenderer, not the BackendRenderer.
See `06-runtime-boundary.md` for `StageResultSignal` and signal emission details.

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
  producedBy:       string | null             // identity that authors the evidence item
}
```

See `06-runtime-boundary.md` for `EvidenceKind`, `CorrelationSpec`,
`EvidenceSuccessCondition`, and `producedBy` definitions.

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
