"""The config-to-artifacts render pipeline shared by ``stagr plan`` and ``stagr apply``.

    config file
      -> static validation, normalization, policies, RenderContext   (render_inputs.py)
      -> Phase 1: per-stage BackendRenderer -> ExecutionPlan -> PlatformRenderer.render_stage
      -> Phase 2: PlatformRenderer.render_routing + render_governance
      -> artifacts (path + bytes) and the StageResultSpecs

The PlatformRenderer writes files, so the pipeline always points it at a private scratch
directory and reads the result back. The target repository is never touched here, which is
what lets ``plan`` and ``apply`` run the exact same code: ``apply`` then copies the artifacts
into the target and ``plan`` only compares them with it.

Nothing is written outside the scratch directory, and every check and every stage renders
before this function returns, so a failure leaves no partial output for the caller to write.
"""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .backend_renderer_registry import BackendRendererNotFoundError
from .errors import RenderPipelineError, SecretAliasResolutionError
from .models import StageResultSpec
from .render_inputs import RenderInputs, load_render_inputs
from .render_loop import run_phase1


@dataclass(frozen=True)
class RenderedArtifact:
    """One generated file: its path inside the platform artifact directory, and its bytes.

    ``relative_path`` is POSIX-style and relative to the platform's artifact directory
    (for GitHub, ``.github/workflows``), so a caller can place it under any output directory.
    """

    relative_path: str
    content: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.content)

    @property
    def sha256_hex(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class RenderPipelineResult:
    """What a successful pipeline run produced. Identical for ``plan`` and ``apply``."""

    platform_name: str
    stage_result_specs: tuple[StageResultSpec, ...]
    artifacts: tuple[RenderedArtifact, ...]
    warnings: tuple[str, ...]
    stage_artifact_glob: str
    stage_artifact_marker: str


def run_render_pipeline(
    config_path: Path,
    project_root: Path,
    platform_override: str | None = None,
) -> RenderPipelineResult:
    """Validate the config at ``config_path`` and render every artifact, writing nothing to the repo.

    Raises:
        RenderPipelineError: For any validation or rendering failure; nothing was rendered
            to a location the caller can observe.
    """
    render_inputs = load_render_inputs(config_path, project_root, platform_override)
    return render_artifacts(render_inputs)


def render_artifacts(render_inputs: RenderInputs) -> RenderPipelineResult:
    """Run Phase 1 and Phase 2 for validated inputs and return the artifacts."""
    platform_target = render_inputs.platform_target
    with tempfile.TemporaryDirectory(prefix="stagr-render-") as scratch_directory:
        scratch_root = Path(scratch_directory)
        platform_renderer = platform_target.create_renderer(scratch_root, render_inputs.publisher_config)
        render_context = render_inputs.render_context
        try:
            stage_result_specs = run_phase1(
                render_context,
                render_inputs.backend_registry,
                platform_renderer,
                render_inputs.raw_config,
            )
            platform_renderer.render_routing(render_context)
            platform_renderer.render_governance(tuple(stage_result_specs), render_context)
        except (ValueError, BackendRendererNotFoundError, SecretAliasResolutionError, OSError) as render_failure:
            raise RenderPipelineError(f"rendering failed: {render_failure}") from render_failure
        artifacts = _collect_artifacts(scratch_root, platform_target.artifact_directory)

    return RenderPipelineResult(
        platform_name=platform_target.name,
        stage_result_specs=tuple(stage_result_specs),
        artifacts=artifacts,
        warnings=render_inputs.warnings,
        stage_artifact_glob=platform_target.stage_artifact_glob,
        stage_artifact_marker=platform_target.stage_artifact_marker,
    )


def _collect_artifacts(scratch_root: Path, artifact_directory: PurePosixPath) -> tuple[RenderedArtifact, ...]:
    """Read back every file the renderer wrote, requiring them all under ``artifact_directory``."""
    artifact_root = scratch_root / artifact_directory
    collected_artifacts: list[RenderedArtifact] = []
    for written_file in sorted(scratch_root.rglob("*")):
        if not written_file.is_file():
            continue
        if not written_file.is_relative_to(artifact_root):
            raise RenderPipelineError(
                f"the platform renderer wrote '{written_file.relative_to(scratch_root).as_posix()}', "
                f"outside its artifact directory '{artifact_directory}'"
            )
        collected_artifacts.append(
            RenderedArtifact(
                relative_path=written_file.relative_to(artifact_root).as_posix(),
                content=written_file.read_bytes(),
            )
        )
    return tuple(collected_artifacts)
