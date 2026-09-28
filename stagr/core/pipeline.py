"""Full normalization pipeline producing NormalizedStage objects.

Implements the end-to-end normalization pipeline (issue #183):

  raw config dict
    → expand_profile_defaults
    → filter_disabled_stages
    → resolve_defaults
    → build_and_validate_dag
    → [to_normalized_stage per stage]
    → tuple[NormalizedStage, ...]

The pipeline runs entirely in the neutral-core vocabulary (no platform-specific
fields).  The caller supplies an already-parsed config dict (e.g. from PyYAML
``safe_load``).  See design-docs/02-canonical-stage-model.md for the pipeline
stage ordering rationale.
"""
from __future__ import annotations

from typing import Any

from .dag import build_and_validate_dag
from .defaults import resolve_defaults
from .enums import StageGate, StageKind, StageTrigger
from .models import NormalizedStage
from .normalize import expand_profile_defaults, filter_disabled_stages
from ..render.constants import BACKEND_GENERIC, PROVIDER_TOOL


def _resolve_backend(stage: dict[str, Any]) -> str:
    """Return the backend string for a fully-resolved stage dict.

    Uses the stage's explicit ``backend`` when set; otherwise derives it from
    the ``PROVIDER_TOOL`` mapping.  Falls back to ``BACKEND_GENERIC`` when the
    provider is absent from the mapping and no explicit backend is given.
    """
    if "backend" in stage:
        return str(stage["backend"])
    provider: str | None = stage.get("provider")
    return PROVIDER_TOOL.get(provider, BACKEND_GENERIC) if provider else BACKEND_GENERIC


def _resolve_gate(stage: dict[str, Any]) -> StageGate:
    """Return the StageGate for a resolved stage dict.

    The raw M1 vocabulary uses ``"blocking"`` and ``"advisory"`` as gate
    strings.  When the gate field is absent or set to ``"advisory"``, the
    stage defaults to ``NON_BLOCKING`` — this is the conservative default that
    does not block merge without an explicit operator declaration.

    Returns:
        ``StageGate.BLOCKING`` when the stage carries ``gate: "blocking"``;
        ``StageGate.NON_BLOCKING`` in all other cases.
    """
    if stage.get("gate") == "blocking":
        return StageGate.BLOCKING
    return StageGate.NON_BLOCKING


def _resolve_trigger(raw_trigger: str, stage_id: str) -> StageTrigger:
    """Return the StageTrigger enum value for a raw M1 config trigger string.

    Uses direct enum construction (``StageTrigger(raw_trigger)``) so any new
    enum variant added to StageTrigger is automatically accepted without
    requiring a manual mapping update.

    Raises:
        ValueError: when ``raw_trigger`` is not a valid StageTrigger value.
    """
    try:
        return StageTrigger(raw_trigger)
    except ValueError:
        valid_trigger_values = [trigger.value for trigger in StageTrigger]
        raise ValueError(
            f"stage '{stage_id}': unrecognised trigger '{raw_trigger}' — "
            f"valid triggers are: {sorted(valid_trigger_values)}"
        )


def _resolve_triggers(stage: dict[str, Any]) -> tuple[StageTrigger, ...]:
    """Return the trigger tuple from a stage's raw ``triggers`` list."""
    stage_id: str = stage.get("id", "<unknown>")
    raw_triggers: list[str] = stage.get("triggers") or []
    return tuple(_resolve_trigger(raw_trigger, stage_id) for raw_trigger in raw_triggers)


def _resolve_stage_kind(raw_type: str | None, stage_id: str) -> StageKind:
    """Return the StageKind enum value for a raw M1 config stage type string.

    Uses direct enum construction (``StageKind(raw_type)``) so any new enum
    variant added to StageKind is automatically accepted without requiring a
    manual mapping update.

    Raises:
        ValueError: when ``raw_type`` is not a valid StageKind value or is absent.
    """
    if raw_type is None:
        raise ValueError(
            f"stage '{stage_id}': required field 'type' is absent"
        )
    try:
        return StageKind(raw_type)
    except ValueError:
        valid_kind_values = [kind.value for kind in StageKind]
        raise ValueError(
            f"stage '{stage_id}': unrecognised type '{raw_type}' — "
            f"valid types are: {sorted(valid_kind_values)}"
        )


def _extract_model_string(model_value: Any) -> str | None:
    """Return a plain model string from a raw stage model value, or None.

    ``resolve_defaults`` may preserve a tiered ``modelBinding`` dict (one
    containing ``tiers``) for downstream tier-selection steps.  This function
    extracts the ``default`` string from such a binding if present, or returns
    ``None`` when no plain string can be determined.  A model value that is
    already a string is returned as-is.
    """
    if isinstance(model_value, str):
        return model_value or None
    if isinstance(model_value, dict):
        default = model_value.get("default")
        return default if isinstance(default, str) and default else None
    return None


def _stage_dict_to_normalized(stage: dict[str, Any]) -> NormalizedStage:
    """Convert a fully-resolved raw stage dict to a ``NormalizedStage``.

    All required fields must already be resolved (provider set, defaults
    applied) before calling this function.  ``build_and_validate_dag`` must
    also have run so dependency references are valid.

    Raises:
        ValueError: when the stage's ``id`` is absent, its ``type`` field is
            not a recognised M1 config stage type, or a trigger string is not
            recognised.
    """
    stage_id: str | None = stage.get("id")
    if not stage_id:
        raise ValueError(
            "stage is missing required 'id' field — "
            "expand_profile_defaults must validate id presence before this step"
        )

    kind = _resolve_stage_kind(stage.get("type"), stage_id)

    return NormalizedStage(
        id=stage_id,
        kind=kind,
        provider=stage["provider"],
        backend=_resolve_backend(stage),
        skill=stage.get("skill") or None,
        gate=_resolve_gate(stage),
        triggers=_resolve_triggers(stage),
        dependencies=tuple(stage.get("depends_on") or []),
        model=_extract_model_string(stage.get("model")),
    )


def normalize_config(config: dict[str, Any]) -> tuple[NormalizedStage, ...]:
    """Run the full normalization pipeline and return all active NormalizedStage objects.

    Pipeline steps (in order):

    1. ``expand_profile_defaults`` — merges profile stage defaults with the
       operator's explicit stage list.
    2. ``filter_disabled_stages`` — removes stages with ``enabled: false``.
    3. ``resolve_defaults`` — applies ``defaults.provider``, ``defaults.backend``,
       and ``defaults.model`` to each active stage.
    4. ``build_and_validate_dag`` — validates dependency references (V-S05) and
       acyclicity (V-S04), then returns stages in topological order.
    5. Convert each stage dict to a ``NormalizedStage`` via
       ``_stage_dict_to_normalized``.

    Args:
        config: A parsed config dict as produced by ``yaml.safe_load`` of a
            valid operator config file.  The function reads ``profile``,
            ``stages``, and ``defaults`` keys.  Unrecognised top-level keys are
            ignored.

    Returns:
        A tuple of ``NormalizedStage`` objects in dependency-first topological
        order.  Disabled stages are never included.

    Raises:
        ValueError: from ``expand_profile_defaults`` when the profile name is
            unrecognised, a stage is missing its ``id``, or duplicate ids are
            present; or from ``_stage_dict_to_normalized`` when a stage type or
            trigger string is not recognised.
        ConfigError: from ``resolve_defaults`` when a stage's provider cannot
            be resolved.
        StaticValidationError: from ``build_and_validate_dag`` when a dependency
            reference is unresolvable (V-S05) or a cycle is detected (V-S04).
    """
    profile_name: str = config.get("profile") or "custom"
    explicit_stages: list[dict[str, Any]] = list(config.get("stages") or [])
    defaults_cfg: dict[str, Any] | None = config.get("defaults")

    expanded_stages = expand_profile_defaults(profile_name, explicit_stages)
    active_stages = filter_disabled_stages(expanded_stages)
    resolved_stages = resolve_defaults(active_stages, defaults_cfg)
    ordered_stages = build_and_validate_dag(resolved_stages)

    return tuple(_stage_dict_to_normalized(stage) for stage in ordered_stages)
