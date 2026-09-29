"""The platforms the render pipeline can target, and how to build each one's renderer.

A :class:`PlatformTarget` bundles what the pipeline must know about a platform without
importing platform code anywhere else: the invocation kinds its renderer supports (V-S08),
the directory its renderer writes artifacts into (relative to the renderer's output root),
the file-name pattern of the per-stage artifacts it owns (used to spot stale ones), and a
factory that builds the renderer. Adding a platform means adding one entry to
``PLATFORM_TARGETS``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from stagr.platforms.github.renderer import GitHubPlatformRenderer

from .enums import InvocationKind
from .errors import RenderPipelineError
from .platform_renderer import PlatformRenderer
from .publisher import PublisherConfig


@dataclass(frozen=True)
class PlatformTarget:
    """Everything the pipeline needs to know about one target platform."""

    name: str
    supported_invocation_kinds: frozenset[InvocationKind]
    artifact_directory: PurePosixPath
    stage_artifact_glob: str
    create_renderer: Callable[[Path, PublisherConfig], PlatformRenderer]


def _create_github_renderer(output_root: Path, publisher_config: PublisherConfig) -> PlatformRenderer:
    return GitHubPlatformRenderer(
        output_dir=output_root,
        publisher_app_id=publisher_config.app_id,
        publisher_private_key_secret=publisher_config.private_key_secret,
    )


PLATFORM_TARGETS: dict[str, PlatformTarget] = {
    "github": PlatformTarget(
        name="github",
        supported_invocation_kinds=GitHubPlatformRenderer.SUPPORTED_INVOCATION_KINDS,
        artifact_directory=PurePosixPath(".github/workflows"),
        stage_artifact_glob="stage-*.yml",
        create_renderer=_create_github_renderer,
    ),
}


def get_platform_target(platform_name: str) -> PlatformTarget:
    """Return the target for ``platform_name`` or raise a clear ``RenderPipelineError``."""
    platform_target = PLATFORM_TARGETS.get(platform_name)
    if platform_target is None:
        supported_names = ", ".join(sorted(PLATFORM_TARGETS))
        raise RenderPipelineError(
            f"platform '{platform_name}' has no PlatformRenderer; supported platforms: {supported_names}"
        )
    return platform_target
