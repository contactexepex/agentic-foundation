"""Tests for the PlatformRenderer Protocol interface (issue #192).

Covers: Protocol conformance, neutral-type-only interface, dry-run mode
(output_dir=None produces no files, render_stage returns StageResultSpec,
render_routing and render_governance raise ValueError in dry-run mode).
"""
from __future__ import annotations

import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_minimal_normalized_stage():
    """Return a valid NormalizedStage for use in stub calls."""
    from stagr.core.models import NormalizedStage
    from stagr.core.enums import StageKind, StageGate, StageTrigger

    return NormalizedStage(
        id="test-stage",
        kind=StageKind.REVIEW,
        provider="anthropic",
        backend="claude",
        skill=None,
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.PR_OPENED,),
        dependencies=(),
    )


def _build_minimal_execution_plan():
    """Return a valid ExecutionPlan with alias-only secrets and gate_disposition set."""
    from stagr.core.models import (
        ExecutionPlan,
        GateDispositionSpec,
        Invocation,
        SecretRef,
    )
    from stagr.core.enums import GateDispositionKind, InvocationKind

    return ExecutionPlan(
        stage_id="test-stage",
        invocation=Invocation(kind=InvocationKind.API_CALL),
        gate_disposition=GateDispositionSpec(
            kind=GateDispositionKind.ALWAYS_PASS,
            selector="always",
        ),
        required_secrets=(SecretRef(alias="PROVIDER_API_KEY"),),
    )


def _build_minimal_render_context():
    """Return a minimal RenderContext for use in stub calls."""
    from stagr.core.models import (
        RenderContext,
        RoutingPolicy,
        MergePolicy,
        TrustPolicy,
        DiscussionPolicy,
    )
    from stagr.core.enums import AuthorRole, ForkPolicy, MergeMode

    stage = _build_minimal_normalized_stage()
    routing_policy = RoutingPolicy(fast_path=None)
    merge_policy = MergePolicy(
        mode=MergeMode.AUTO,
        blocking_stage_ids=(stage.id,),
        require_head_bound=True,
        discussion_policy=DiscussionPolicy(require_resolved=False),
    )
    trust_policy = TrustPolicy(
        trusted_roles=(AuthorRole.OWNER,),
        fork_policy=ForkPolicy.DENY,
        human_merge_label="human-merge",
    )
    return RenderContext(
        stages=(stage,),
        routing_policy=routing_policy,
        merge_policy=merge_policy,
        trust_policy=trust_policy,
        platform="github",
        config_version="1",
    )


def _build_minimal_stage_result_spec():
    """Return a minimal StageResultSpec."""
    from stagr.core.models import StageResultSpec, StageResultProvenance
    from stagr.core.enums import StageResultSignalKind

    return StageResultSpec(
        stage_id="test-stage",
        signal_kind=StageResultSignalKind.CHECK_RUN,
        signal_selector="test/check",
        provenance=StageResultProvenance(publisher_identity="github-app[bot]"),
    )


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubPlatformRenderer:
    """Minimal PlatformRenderer implementation for conformance and dry-run testing.

    Accepts output_dir: Path | None. When None (dry-run), render_stage returns
    a StageResultSpec without writing files; render_routing and render_governance
    raise ValueError. All writes are recorded in written_paths for test inspection.
    """

    def __init__(self, output_dir: Path | None) -> None:
        self._output_dir = output_dir
        self.written_paths: list[Path] = []

    def render_stage(
        self,
        plan: "ExecutionPlan",  # noqa: F821
        stage: "NormalizedStage",  # noqa: F821
        render_context: "RenderContext",  # noqa: F821
    ) -> "StageResultSpec":  # noqa: F821
        if self._output_dir is not None:
            artifact_path = self._output_dir / f"{stage.id}.yml"
            artifact_path.write_text("# stub artifact\n")
            self.written_paths.append(artifact_path)
        return _build_minimal_stage_result_spec()

    def render_routing(self, render_context: "RenderContext") -> None:  # noqa: F821
        if self._output_dir is None:
            raise ValueError(
                "render_routing cannot be called in dry-run mode (output_dir is None)"
            )
        routing_path = self._output_dir / "routing.yml"
        routing_path.write_text("# stub routing\n")
        self.written_paths.append(routing_path)

    def render_governance(
        self,
        result_specs: "tuple[StageResultSpec, ...]",  # noqa: F821
        render_context: "RenderContext",  # noqa: F821
    ) -> None:
        if self._output_dir is None:
            raise ValueError(
                "render_governance cannot be called in dry-run mode (output_dir is None)"
            )
        governance_path = self._output_dir / "governance.yml"
        governance_path.write_text("# stub governance\n")
        self.written_paths.append(governance_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_platform_renderer_protocol_conformance() -> None:
    """A minimal stub satisfies the PlatformRenderer Protocol (runtime isinstance check)."""
    from stagr.core.platform_renderer import PlatformRenderer

    stub = _StubPlatformRenderer(output_dir=None)

    assert isinstance(stub, PlatformRenderer), (
        f"_StubPlatformRenderer must be recognised as a PlatformRenderer by isinstance(); "
        f"got type {type(stub)}"
    )


def test_platform_renderer_interface_uses_only_neutral_types() -> None:
    """Every PlatformRenderer method annotation is a neutral-core type or composition thereof.

    Inspects the actual public method signatures of PlatformRenderer using
    typing.get_type_hints so that introducing a platform-specific annotation
    (e.g. a GitHub workflow type) would fail this test.

    Approved annotations: ExecutionPlan, NormalizedStage, RenderContext,
    StageResultSpec, NoneType, and tuple[<neutral>, ...].
    """
    import typing

    from stagr.core.platform_renderer import PlatformRenderer
    from stagr.core.models import (
        ExecutionPlan,
        NormalizedStage,
        RenderContext,
        StageResultSpec,
    )

    neutral_types = frozenset({ExecutionPlan, NormalizedStage, RenderContext, StageResultSpec})

    def _is_neutral(annotation: object) -> bool:
        """Return True if annotation is composed only of neutral types or NoneType/tuple."""
        if annotation is type(None):
            return True
        if annotation in neutral_types:
            return True
        origin = typing.get_origin(annotation)
        if origin is tuple:
            return all(
                arg is Ellipsis or _is_neutral(arg)
                for arg in typing.get_args(annotation)
            )
        return False

    public_methods = ("render_stage", "render_routing", "render_governance")
    for method_name in public_methods:
        method = getattr(PlatformRenderer, method_name)
        hints = typing.get_type_hints(method)
        for param_name, annotation in hints.items():
            if param_name == "self":
                continue
            assert _is_neutral(annotation), (
                f"PlatformRenderer.{method_name} parameter/return '{param_name}' has "
                f"non-neutral annotation {annotation!r}; only neutral-core types are "
                f"permitted in the PlatformRenderer interface"
            )


def test_platform_renderer_dry_run_render_stage_returns_spec() -> None:
    """render_stage returns a StageResultSpec in dry-run mode (output_dir=None)."""
    from stagr.core.models import StageResultSpec

    stub = _StubPlatformRenderer(output_dir=None)
    plan = _build_minimal_execution_plan()
    stage = _build_minimal_normalized_stage()
    render_context = _build_minimal_render_context()

    result = stub.render_stage(plan, stage, render_context)

    assert isinstance(result, StageResultSpec), (
        f"render_stage must return a StageResultSpec in dry-run mode; "
        f"got {type(result)!r}"
    )


def test_platform_renderer_dry_run_produces_no_files() -> None:
    """A concrete renderer with output_dir=None writes no files during render_stage.

    Uses a positive control to confirm the same stub DOES write when given a real
    output_dir, making the dry-run assertion non-vacuous.
    """
    plan = _build_minimal_execution_plan()
    stage = _build_minimal_normalized_stage()
    render_context = _build_minimal_render_context()

    with tempfile.TemporaryDirectory() as temp_directory:
        output_dir = Path(temp_directory)

        # Positive control: the stub writes when output_dir is a real path.
        live_stub = _StubPlatformRenderer(output_dir=output_dir)
        live_stub.render_stage(plan, stage, render_context)
        assert live_stub.written_paths, (
            "positive control: live stub must record at least one write"
        )
        assert list(output_dir.iterdir()), (
            "positive control: output_dir must contain written files"
        )

    # Dry-run: output_dir=None — the stub must not record any writes.
    dry_run_stub = _StubPlatformRenderer(output_dir=None)
    dry_run_stub.render_stage(plan, stage, render_context)

    assert not dry_run_stub.written_paths, (
        f"render_stage in dry-run mode must not write any files; "
        f"recorded writes: {dry_run_stub.written_paths}"
    )


def test_platform_renderer_non_dry_run_render_stage_writes_file() -> None:
    """A concrete renderer with a real output_dir writes a file during render_stage."""
    from stagr.core.models import StageResultSpec

    plan = _build_minimal_execution_plan()
    stage = _build_minimal_normalized_stage()
    render_context = _build_minimal_render_context()

    with tempfile.TemporaryDirectory() as temp_directory:
        output_dir = Path(temp_directory)
        stub = _StubPlatformRenderer(output_dir=output_dir)

        result = stub.render_stage(plan, stage, render_context)

        assert isinstance(result, StageResultSpec), (
            f"render_stage must return StageResultSpec; got {type(result)!r}"
        )
        assert list(output_dir.iterdir()), (
            "render_stage with a real output_dir must write at least one file"
        )


def test_platform_renderer_dry_run_render_routing_raises_value_error() -> None:
    """render_routing raises ValueError when called in dry-run mode (output_dir=None)."""
    stub = _StubPlatformRenderer(output_dir=None)
    render_context = _build_minimal_render_context()

    try:
        stub.render_routing(render_context)
        assert False, (  # noqa: B011
            "render_routing must raise ValueError when output_dir is None (dry-run mode)"
        )
    except ValueError:
        pass  # expected


def test_platform_renderer_dry_run_render_governance_raises_value_error() -> None:
    """render_governance raises ValueError when called in dry-run mode (output_dir=None)."""
    stub = _StubPlatformRenderer(output_dir=None)
    render_context = _build_minimal_render_context()
    result_spec = _build_minimal_stage_result_spec()

    try:
        stub.render_governance((result_spec,), render_context)
        assert False, (  # noqa: B011
            "render_governance must raise ValueError when output_dir is None (dry-run mode)"
        )
    except ValueError:
        pass  # expected
