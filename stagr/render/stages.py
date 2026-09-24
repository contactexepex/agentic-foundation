"""Stage-graph expansion: load `from` agent presets, merge the profile's stages with explicit
stages, and fill each stage's effective backend from its provider."""
from __future__ import annotations

from typing import Any

from .constants import AGENTS_DIR, PROFILE_STAGES, PROVIDER_TOOL
from .errors import RenderError
from .util import _deep_merge, _read_yaml


def _load_agent_preset(name: str) -> dict[str, Any]:
    # `from` comes from the (untrusted) config; an absolute/`..`/symlink value could escape
    # AGENTS_DIR and read a host YAML file into the rendered workflow/invocation. Resolve the
    # final path (follows symlinks) and reject anything outside the presets directory.
    resolved = (AGENTS_DIR / f"{name}.yml").resolve()
    if not resolved.is_relative_to(AGENTS_DIR.resolve()):
        raise RenderError(f"agent preset '{name}' resolves outside the presets directory")
    if not resolved.is_file():
        raise RenderError(f"agent preset '{name}' not found at {resolved}")
    return _read_yaml(resolved)


def expand_stages(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand `from` presets and merge the profile's stages with explicit stages."""
    profile = cfg.get("profile", "standard")
    if profile not in PROFILE_STAGES:
        raise RenderError(f"unknown profile: {profile}")
    stages_by_id = {stage_def["id"]: dict(stage_def) for stage_def in PROFILE_STAGES[profile]}
    order = [stage_def["id"] for stage_def in PROFILE_STAGES[profile]]
    explicit_ids: set[str] = set()
    for stage in cfg.get("stages", []) or []:
        stage_id = stage.get("id")
        if not stage_id:
            raise RenderError("every stage needs an id")
        # Two explicit stages sharing an id would silently deep-merge into a hybrid stage and drop
        # a graph node; reject it. (Overriding a PROFILE-provided stage by id is still allowed.)
        if stage_id in explicit_ids:
            raise RenderError(f"duplicate explicit stage id '{stage_id}'")
        explicit_ids.add(stage_id)
        resolved = dict(stage)
        # `from` supplies preset defaults; the stage's own fields override them.
        if "from" in resolved:
            preset = _load_agent_preset(resolved["from"])
            resolved = _deep_merge(preset, {k: v for k, v in resolved.items() if k != "from"})
            resolved["id"] = stage_id
        if stage_id in stages_by_id:
            stages_by_id[stage_id] = _deep_merge(stages_by_id[stage_id], resolved)
        else:
            stages_by_id[stage_id] = resolved
            order.append(stage_id)
    expanded = [stages_by_id[stage_id] for stage_id in order if stages_by_id[stage_id].get("enabled", True)]
    _apply_backend_defaults(cfg, expanded)
    return expanded


def _apply_backend_defaults(cfg: dict[str, Any], stages: list[dict[str, Any]]) -> None:
    """Fill each stage's effective backend/tool from its provider when it does not pin one.

    Provider is the primary knob: a stage that names `provider` (or inherits `defaults.provider`)
    gets the tool the toolkit renders for that provider (anthropic -> Claude Code, openai -> Codex).
    An explicit `stages[].backend` wins (override / custom adapter). A stage whose provider has no
    known tool is left without one (`_stage_backend` -> the generic runner), so an unsupported or
    roadmap provider never silently masquerades as a supported tool.
    """
    default_provider = (cfg.get("defaults", {}) or {}).get("provider")
    for stage in stages:
        if (stage.get("backend") or {}).get("name"):
            continue
        tool = PROVIDER_TOOL.get(stage.get("provider") or default_provider)
        if tool:
            stage["backend"] = {"name": tool}
