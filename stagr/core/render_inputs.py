"""Config file to validated ``RenderContext``: the static validation pass (V-S01 to V-S12).

``load_render_inputs`` is the front half of the render pipeline and only reads from the
filesystem. It is shared by ``stagr plan`` and ``stagr apply`` through
:mod:`stagr.core.render_pipeline`, and is the entry point ``stagr doctor`` will call before
its environment checks.

Order (fail fast, the first failing check raises ``RenderPipelineError``):

1. read + parse YAML, version must be the integer 2 (V-S02)
2. resolve ``extends`` bases (confined to the project root)
3. JSON Schema validity (V-S01)
4. normalization: duplicate ids (V-S03), dependency references (V-S05), cycles (V-S04)
5. skill file existence (V-S06)
6. trust / routing / merge policy derivation (V-S14 trusted roles)
7. publisher configuration (the neutral pipeline requires ``platform.publisher``)
8. BackendRenderer availability (V-S07), platform invocation kinds (V-S08),
   route dependency-closure (V-S09), non-empty blocking stages for auto-merge (V-S10)
9. dormant routing configuration (V-S11) is collected as a warning, not an error

V-S12 (secret alias resolution) cannot fail in the neutral pipeline: the Phase 1 alias
resolver always ends in the convention fallback (the alias is the secret name), so every
alias resolves. Whether the resolved secrets exist is a ``stagr doctor`` concern.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from ..render.config import describe_schema_error, resolve_extends
from ..render.constants import SCHEMA_PATH
from ..render.errors import RenderError
from ..render.util import confine_config_path
from .backend_renderer_registry import BackendRendererRegistry
from .config_parser import parse_config
from .errors import ConfigVersionError, RenderPipelineError
from .models import ConfigError, RenderContext, StaticValidationError
from .pipeline import normalize_config
from .platform_targets import PlatformTarget, get_platform_target
from .policy import (
    default_normal_route_to_all_stages,
    derive_merge_policy,
    derive_routing_policy,
    derive_trust_policy,
)
from .publisher import PublisherConfig, derive_publisher_config
from .renderers.anthropic_claude_backend_renderer import AnthropicClaudeBackendRenderer
from .renderers.openai_codex_backend_renderer import OpenAICodexBackendRenderer
from .skill_validator import validate_skill_file_existence
from .static_validator import (
    collect_dormant_routing_warnings,
    collect_profile_shortcut_warnings,
    collect_unenforced_merge_warnings,
    collect_placeholder_invocation_warnings,
    validate_backend_renderer_availability,
    validate_blocking_stages_run_their_backend,
    validate_fast_path_restrictions_are_enforceable,
    validate_merge_policy_has_blocking_stages,
    validate_merge_settings_are_enforceable,
    validate_platform_invocation_compatibility,
    validate_route_dependency_closure,
)

DEFAULT_PLATFORM_NAME = "github"
# Mirrors the `profile` default in stagr/config.schema.json.
SCHEMA_DEFAULT_PROFILE = "standard"


@dataclass(frozen=True)
class RenderInputs:
    """Everything the rendering phases need, produced by a passing static validation."""

    raw_config: dict[str, Any]
    render_context: RenderContext
    publisher_config: PublisherConfig
    backend_registry: BackendRendererRegistry
    platform_target: PlatformTarget
    warnings: tuple[str, ...]


def build_default_backend_registry() -> BackendRendererRegistry:
    """Return a new registry holding the BackendRenderers that ship with Stagr."""
    backend_registry = BackendRendererRegistry()
    backend_registry.register(AnthropicClaudeBackendRenderer())
    backend_registry.register(OpenAICodexBackendRenderer())
    return backend_registry


def load_render_inputs(
    config_path: Path,
    project_root: Path,
    platform_override: str | None = None,
) -> RenderInputs:
    """Read ``config_path`` and run the full static validation pass.

    Args:
        config_path: The ``.agentic/config.yml`` to read; must resolve inside the
            current working directory (the project root).
        project_root: Directory holding ``.agentic/`` (skill files are resolved from it).
        platform_override: Replaces ``platform.type`` when given.

    Raises:
        RenderPipelineError: On the first failing check, with a message naming the check.
    """
    try:
        return _load_render_inputs(config_path, project_root, platform_override)
    except RenderPipelineError:
        raise
    except ConfigVersionError as version_error:
        raise RenderPipelineError(f"V-S02: {version_error}") from version_error
    except (StaticValidationError, ConfigError, RenderError, ValueError) as validation_error:
        raise RenderPipelineError(str(validation_error)) from validation_error


def _load_render_inputs(
    config_path: Path,
    project_root: Path,
    platform_override: str | None,
) -> RenderInputs:
    raw_config = _read_config(config_path)
    _validate_against_schema(raw_config)

    platform_name = platform_override or (raw_config.get("platform") or {}).get("type") or DEFAULT_PLATFORM_NAME
    platform_target = get_platform_target(platform_name)

    # The schema's default profile is `standard`; normalize_config's own fallback is `custom`, which would
    # let a config that omits `profile` pass with no review or security stage at all.
    raw_config.setdefault("profile", SCHEMA_DEFAULT_PROFILE)
    normalized_stages = normalize_config(raw_config)
    validate_skill_file_existence(
        [{"id": stage.id, "skill": stage.skill} for stage in normalized_stages], project_root
    )

    trust_policy = derive_trust_policy(raw_config)
    routing_policy = default_normal_route_to_all_stages(derive_routing_policy(raw_config), normalized_stages)
    merge_policy = derive_merge_policy(raw_config, normalized_stages, trust_policy)
    publisher_config = _derive_publisher_or_explain(raw_config)

    backend_registry = build_default_backend_registry()
    validate_backend_renderer_availability(normalized_stages, backend_registry)
    validate_platform_invocation_compatibility(
        normalized_stages, backend_registry, platform_target.supported_invocation_kinds
    )
    validate_blocking_stages_run_their_backend(
        normalized_stages, backend_registry, platform_target.functional_invocation_kinds
    )
    validate_route_dependency_closure(routing_policy, normalized_stages)
    validate_merge_policy_has_blocking_stages(merge_policy)
    validate_merge_settings_are_enforceable(raw_config)
    validate_fast_path_restrictions_are_enforceable(raw_config)

    render_context = RenderContext(
        stages=normalized_stages,
        routing_policy=routing_policy,
        merge_policy=merge_policy,
        trust_policy=trust_policy,
        platform=platform_target.name,
        config_version=str(raw_config["version"]),
    )
    return RenderInputs(
        raw_config=raw_config,
        render_context=render_context,
        publisher_config=publisher_config,
        backend_registry=backend_registry,
        platform_target=platform_target,
        warnings=collect_dormant_routing_warnings(raw_config)
        + collect_unenforced_merge_warnings(raw_config)
        + collect_profile_shortcut_warnings(raw_config)
        + collect_placeholder_invocation_warnings(
            normalized_stages, backend_registry, platform_target.functional_invocation_kinds
        ),
    )


def _read_config(config_path: Path) -> dict[str, Any]:
    """Confine, read, version-check (V-S02), and extends-resolve the config file."""
    confined_config_path = confine_config_path(config_path)
    try:
        raw_config = parse_config(confined_config_path)
    except FileNotFoundError as missing_file:
        raise RenderPipelineError(f"config file not found: {config_path}") from missing_file
    except OSError as unreadable_file:
        raise RenderPipelineError(f"cannot read config file {config_path}: {unreadable_file}") from unreadable_file
    except yaml.YAMLError as invalid_yaml:
        raise RenderPipelineError(f"{config_path} is not valid YAML: {invalid_yaml}") from invalid_yaml
    return resolve_extends(raw_config, confined_config_path.parent)


def _validate_against_schema(raw_config: dict[str, Any]) -> None:
    """V-S01: the config must conform to ``stagr/config.schema.json``."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(raw_config), key=lambda error: list(error.path))
    if schema_errors:
        error_details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '(root)'}: {describe_schema_error(error)}"
            for error in schema_errors
        )
        raise RenderPipelineError(f"V-S01: config does not conform to schema: {error_details}")


def _derive_publisher_or_explain(raw_config: dict[str, Any]) -> PublisherConfig:
    try:
        return derive_publisher_config(raw_config)
    except ConfigError as publisher_error:
        raise RenderPipelineError(
            f"{publisher_error} (the render pipeline needs platform.publisher to render "
            "the stage, routing, and governance workflows)"
        ) from publisher_error
