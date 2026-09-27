"""Neutral core data models.

All models are immutable dataclasses. No platform-specific fields appear here
(no GitHub event names, no permissions: strings, no CI YAML keys). The policy
models (TrustPolicy, RoutingPolicy, MergePolicy) are defined here as data
structures; their derivation logic lives in stagr/core/policy.py (Group C).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import (
    AuthorRole,
    EvidenceKind,
    ForkPolicy,
    InvocationKind,
    MergeMode,
    StageGate,
    StageKind,
    StageResultConclusion,
    StageResultSignalKind,
    StageResultState,
    StageTrigger,
)

# ---------------------------------------------------------------------------
# NormalizedStage (#174)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedStage:
    """Fully-resolved, platform-agnostic stage produced by the normalization pipeline.

    No `enabled` field — stages with enabled:false are removed before this object
    is constructed. All fields are fully typed; no raw dicts.
    """

    id: str
    kind: StageKind
    provider: str
    backend: str
    skill: str
    gate: StageGate
    triggers: tuple[StageTrigger, ...]
    dependencies: tuple[str, ...]  # stage ids; validity enforced by V-S05
    model: str | None = None       # None = backend decides


# ---------------------------------------------------------------------------
# ExecutionPlan and Invocation (#175)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Invocation:
    """How the backend is asked to execute the stage.

    `params` is backend-defined and opaque to the neutral contract. The
    PlatformRenderer interprets the params for each supported InvocationKind.
    No platform-specific field names appear here.
    """

    kind: InvocationKind
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Make params immutable for frozen dataclass compatibility.
        object.__setattr__(self, "params", dict(self.params))


@dataclass(frozen=True)
class GateDispositionSpec:
    """How to determine PASS vs BLOCKED at run time.

    Separates "is the stage done?" (EvidenceSpec) from "given it is done, is
    the result PASS or BLOCKED?". Backend-defined; opaque to the neutral contract
    beyond this structure. `kind` identifies the disposition strategy; `params`
    carries backend-specific details.
    """

    kind: str                         # e.g. "conclusion_field", "exit_code"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", dict(self.params))


@dataclass(frozen=True)
class CorrelationSpec:
    """How a piece of evidence is correlated to a specific stage invocation.

    `field` names a backend-supplied discriminator that the GitHub API actually
    exposes (e.g., pull_request_review_id). `value` is the expected value.
    Both are backend-defined and opaque to the neutral contract.
    """

    field: str
    value: str


@dataclass(frozen=True)
class EvidenceSuccessCondition:
    """What raw backend output counts as the stage having processed a head commit.

    `operator` is one of: "equals", "contains", "matches_regex", "present".
    `value` is the expected value or pattern (None when operator is "present").
    """

    operator: str
    value: str | None = None


@dataclass(frozen=True)
class EvidenceSpec:
    """How stage completion is detected at run time.

    Backend-supplied; consumed by the PlatformRenderer writing the stage
    execution artifact. Uses semantic vocabulary — not platform-object names.
    `selector` is backend-defined and opaque to the neutral contract.
    """

    kind: EvidenceKind
    selector: str                         # backend-defined, opaque
    correlation: CorrelationSpec
    success_condition: EvidenceSuccessCondition


@dataclass(frozen=True)
class SecretRef:
    """A backend-declared secret requirement.

    `alias` is the backend-defined opaque name (e.g., "CODEX_API_KEY").
    `env_name` is the resolved platform secret name (e.g., "OPENAI_API_KEY").
    """

    alias: str
    env_name: str


@dataclass(frozen=True)
class ExecutionPlan:
    """Intermediate representation between BackendRenderer and PlatformRenderer.

    Opaque to the neutral contract beyond this structure. No platform-specific
    fields (no permissions:, no GitHub event names). `gate_disposition` is
    required — an ExecutionPlan without it is invalid.
    """

    stage_id: str
    invocation: Invocation
    gate_disposition: GateDispositionSpec
    required_secrets: tuple[SecretRef, ...] = ()
    evidence: tuple[EvidenceSpec, ...] = ()

    def __post_init__(self) -> None:
        # Enforce required field at construction time.
        if self.gate_disposition is None:
            raise ValueError(
                f"ExecutionPlan for stage '{self.stage_id}' must have gate_disposition set"
            )


# ---------------------------------------------------------------------------
# StageResultSpec and StageResultSignal (#177)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageResultProvenance:
    """Expected publisher identity for governance verification.

    On GitHub, this is the GitHub App installation ID or a stable workflow
    identity that created the Check Run. The governance artifact must reject
    any signal whose publisher identity does not match the rendered provenance.
    """

    publisher_identity: str


@dataclass(frozen=True)
class StageResultSpec:
    """Render-time declaration of how a stage will signal its result at run time.

    Produced by the PlatformRenderer during Phase 1. Phase 2 uses this to
    generate the governance artifact without reading raw EvidenceSpec details.
    Signal locations are platform primitives; they are determined by the
    PlatformRenderer, not the BackendRenderer.
    """

    stage_id: str
    signal_kind: StageResultSignalKind
    signal_selector: str              # platform-specific locator
    provenance: StageResultProvenance


@dataclass(frozen=True)
class StageResultSignal:
    """Run-time value emitted by a stage execution artifact.

    headSha binding is mandatory — a StageResultSignal without headSha cannot
    be safely consumed (a stale signal for a prior commit could satisfy the gate
    for a new commit).
    """

    stage_id: str
    head_sha: str
    state: StageResultState
    conclusion: StageResultConclusion

    def __post_init__(self) -> None:
        if not self.head_sha:
            raise ValueError(
                f"StageResultSignal for stage '{self.stage_id}' must have head_sha set"
            )


# ---------------------------------------------------------------------------
# Policy models (#178 stubs — derivation logic in policy.py, Group C)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrustPolicy:
    """Who and what Stagr-generated automation may act on behalf of."""

    trusted_roles: tuple[AuthorRole, ...]
    fork_policy: ForkPolicy
    human_merge_label: str


@dataclass(frozen=True)
class PathMatchSpec:
    """Glob patterns for route classification."""

    paths: tuple[str, ...]


@dataclass(frozen=True)
class RouteStageMap:
    """Stage id sets for each route."""

    fast: tuple[str, ...]
    normal: tuple[str, ...]


@dataclass(frozen=True)
class FastPathPolicy:
    """Route classification rules when fast_path is enabled."""

    match: PathMatchSpec
    stages: RouteStageMap


@dataclass(frozen=True)
class RoutingPolicy:
    """How changed file paths are classified into route classes.

    `fast_path` is None when fast_path.enabled: false (or routing is absent).
    """

    fast_path: FastPathPolicy | None


@dataclass(frozen=True)
class DiscussionPolicy:
    """Neutral representation of the unresolved-discussions requirement."""

    require_resolved: bool


@dataclass(frozen=True)
class ExternalGate:
    """V1 external gate: an observed check run not managed by Stagr.

    V1 semantics: when the check run is present on the current head SHA, it
    must be in the required terminal conclusion; when absent, it is tolerated
    (fail-open). Provenance verification is V2 scope.
    """

    check_run_name: str
    required_presence: str    # "when_present" (V1 fixed)
    required_conclusion: str  # "success" (V1 fixed)


@dataclass(frozen=True)
class MergePolicy:
    """Merge eligibility requirements. Derived at normalization time; never re-derived at run time."""

    mode: MergeMode
    blocking_stage_ids: tuple[str, ...]
    require_head_bound: bool              # always True in V1
    discussion_policy: DiscussionPolicy | None = None
    external_gates: tuple[ExternalGate, ...] = ()


# ---------------------------------------------------------------------------
# RenderContext (#178)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderContext:
    """Complete input to every renderer. Assembled by the Stagr CLI; never modified by renderers.

    StageResultSpec[] is NOT here — it is produced during Phase 1 and collected
    by the CLI before Phase 2 begins.
    """

    stages: tuple[NormalizedStage, ...]
    routing_policy: RoutingPolicy
    merge_policy: MergePolicy
    trust_policy: TrustPolicy
    platform: str          # e.g. "github", "gitlab" — plain string, no enum
    config_version: str
