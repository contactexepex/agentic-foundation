"""PlatformRenderer Protocol interface.

Defines the contract every platform renderer must satisfy. A PlatformRenderer
maps an ExecutionPlan and NormalizedStage to platform-specific artifacts in
two phases:

  Phase 1  — render_stage: write the stage execution artifact; return its
              StageResultSpec for use in Phase 2.
  Phase 2a — render_routing: write the routing artifact (path classification
              workflow) from the RenderContext.
  Phase 2b — render_governance: write the governance artifact from collected
              StageResultSpecs.

Concrete renderers must accept ``output_dir: Path | None``; ``None`` signals
dry-run mode where no files are written. ``render_routing`` and
``render_governance`` must raise ``ValueError`` when called in dry-run mode;
``render_stage`` returns a ``StageResultSpec`` in both modes.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import ExecutionPlan, NormalizedStage, RenderContext, StageResultSpec


@runtime_checkable
class PlatformRenderer(Protocol):
    """Writes platform-specific artifacts from neutral-core render inputs.

    Implementations write CI platform artifacts (workflows, gate checks) from
    neutral-core data types. No platform-specific types appear in the
    interface; they are internal to each concrete implementation.
    """

    def render_stage(
        self,
        plan: ExecutionPlan,
        stage: NormalizedStage,
        render_context: RenderContext,
    ) -> StageResultSpec:
        """Phase 1: write the stage execution artifact; return its StageResultSpec."""
        ...

    def render_routing(
        self,
        render_context: RenderContext,
    ) -> None:
        """Phase 2a: write the routing artifact (path classification workflow)."""
        ...

    def render_governance(
        self,
        result_specs: tuple[StageResultSpec, ...],
        render_context: RenderContext,
    ) -> None:
        """Phase 2b: write the governance artifact from collected StageResultSpecs."""
        ...
