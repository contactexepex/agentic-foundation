# Stagr Neutral Core — Render-Time Architecture

**Status:** Target design. What is built today is in
[ARCHITECTURE.md, section 8](../docs/ARCHITECTURE.md#8-status--roadmap).

---

## Overview

Render time is when Stagr translates the neutral config into platform-native artifacts.
It happens once per config change, triggered by `stagr apply`. After rendering, Stagr
has no further involvement; the generated artifacts, including the rules engine file, run
entirely inside the target platform (`06-runtime-boundary.md`).

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
BackendRenderer(provider, backend)     for an agent executor
built-in check planner                 for a commands or observed executor (09-check-stages.md)
      │  produces
      ▼
ExecutionPlan { stageId, invocation, requiredSecrets, evidence, gateDisposition }
      │
      ▼
PlatformRenderer
      │  produces
      ├── Stage execution artifact (e.g., one CI workflow file per stage)
      └── StageResultSpec  (how this stage signals its result at run time)
```

Each `(ExecutionPlan, NormalizedStage)` pair is processed independently. The
PlatformRenderer returns the stage execution artifact **and** a `StageResultSpec`
describing the platform-native signal location where the artifact will publish
`StageResultSignal` values.

**Renderers return artifacts; they never write files.** Every PlatformRenderer method returns
`RenderedArtifact { path, content }` values (`path` is a POSIX path relative to the repository
root). The Stagr CLI decides what to do with them: `stagr plan` lists them, `stagr apply` writes
them. Because both commands call the same renderer methods and only differ in that last step,
a plan can never disagree with what apply writes.

### Phase 2 — Pipeline: governance artifacts from collected StageResultSpecs

After all stages in Phase 1 are processed, the collected `StageResultSpec[]` are
available. Phase 2 uses them along with the pipeline policies:

```
RoutingPolicy + MergePolicy + TrustPolicy + StageResultSpec[]
      │
      ▼
PlatformRenderer
      │  returns
      ▼
Routing artifact + Governance artifact
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
  scm:           string                 // platform.scm: where changes, the gate and identities live
  ci:            string                 // platform.ci: where jobs run; equals scm unless set
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

| Value | Semantics |
|---|---|
| `COMMENT_COMMAND` | Post a comment on the change to trigger the backend |
| `CI_STEP` | Insert a native CI step provided by the platform or the backend. **Platform-dependent by design**; validation (V-S08) catches incompatibilities at render time. |
| `RUN_COMMANDS` | Run the stage's commands in a CI job with no credentials and no secrets (`commands` executor) |
| `READ_RESULT` | Read a named result from a named producer (`observed` executor); starts nothing |

How each kind is rendered on GitHub is in `08-github-codex-mapping.md`.

### StageResultSpec

A `StageResultSpec` is the render-time declaration of how a stage will signal its
result at run time. Path 2 uses this to generate the governance artifact without
reading raw `EvidenceSpec` details.

```
StageResultSpec {
  stageId:        string
  signalSelector: string                  // platform-specific locator of the result carrier
  provenance:     StageResultProvenance   // expected publisher identity for governance verification
}

StageResultProvenance {
  publisherIdentity: string   // platform-specific identity of the expected signal publisher
}
```

The signal is published on a result carrier bound to the revision and written by the publisher
identity; the provenance rule is in `06-runtime-boundary.md`, "Signal emission". The carrier
and the permissions it needs are platform primitives, so they are chosen by the
PlatformRenderer and never appear in `ExecutionPlan`. The GitHub carrier and its permissions are
in `08-github-codex-mapping.md`.

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
must decide the gate result. Without a normalized signal between them, the governance
artifact must understand every possible backend's raw output format — breaking
provider-neutrality.

### The solution: StageResultSignal

At run time, each stage execution artifact **emits a `StageResultSignal`** to the location its
`StageResultSpec` declares. The governance artifact reads these signals, not raw evidence. The
signal, its states, conclusions and reasons are defined in `06-runtime-boundary.md`.

### Signal flow

```
Stage execution artifact (runtime)
    ├── Detects raw backend evidence (via EvidenceSpec)
    ├── Determines state and conclusion
    └── Emits StageResultSignal
            │
            ▼ (result carrier written by the publisher identity)
Governance artifact (runtime)
    ├── Reads StageResultSignal for each blockingStageId
    ├── Evaluates the gate (06-runtime-boundary.md, "Gate evaluation")
    └── Publishes the one gate result
```

---

## Three artifact classes

| Class | Produced by | Responsibility |
|---|---|---|
| **Stage execution artifact** | Path 1, one per stage | Trigger on declared StageTriggers; invoke the backend or run the work; detect evidence; emit StageResultSignal |
| **Routing artifact** | Path 2 | Classify changed files; emit `RouteClassification` signal |
| **Governance artifact** | Path 2 | Read `StageResultSignal` for each blocking stage + `RouteClassification`; enforce `MergePolicy`; publish the one gate result. It never merges. |

The GitHub file names are in `08-github-codex-mapping.md`.

---

## Four authority rules

1. **Normalized stage graph** owns execution semantics: what runs, when, and with what
   dependency ordering.
2. **RoutingPolicy** owns stage applicability: which stages run on FAST vs NORMAL routes.
3. **EvidenceSpec** owns raw completion detection: what backend output counts as the
   stage having processed a given revision.
4. **MergePolicy** owns the gate requirements: which stages must have `conclusion = PASS`
   for the revision's gate result to pass.

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
