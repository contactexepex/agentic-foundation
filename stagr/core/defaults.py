"""Backend and model default resolution for the neutral-core normalization pipeline.

Implements the third step of the normalization pipeline (issue #181): after profile
expansion and disabled-stage filtering, each active stage's ``provider``, ``backend``,
and ``model`` fields are resolved against ``defaults`` from the operator config.

**Resolution order:**

1. ``provider``: if the stage has no ``provider`` key, apply ``defaults.provider``.
2. ``backend``: if the stage has no ``backend`` key, apply ``defaults.backend`` (when present).
3. ``model``: if the stage has no ``model`` key, look up
   ``defaults.models[resolved_provider]``.  If that binding contains ``tiers``,
   the full binding is applied (deep-copied) so the downstream tier-selection step
   can pick the right model string; otherwise its ``default`` string is applied.
   If the stage already has a ``model`` key that is a ``modelBinding`` object
   (per the config schema ``stage.model → modelBinding``), a binding that has only
   a ``default`` key (no ``tiers``) is normalized to that plain string.  A binding
   that contains ``tiers`` — whether or not it also has ``default`` — is preserved
   unchanged so the downstream tier-selection step can use the full binding.

After resolution, every stage must have a non-empty ``provider``; stages that still
lack one raise ``ConfigError``.  The absence of ``backend`` is **not** an error at
this layer — per-provider backend defaults are registered in the BackendRenderer
registry and applied in a later normalization step.

**Vocabulary layer:** operates in the raw M1 config vocabulary (``depends_on``, not
``dependencies``; string literals for gate values, not enum instances).

Design source: design-docs/03-provider-backend-model.md
"""
from __future__ import annotations

import copy
from typing import Any

from .models import ConfigError


def _resolve_model_binding(binding: dict[str, Any]) -> dict[str, Any] | str | None:
    """Return the normalized value from a modelBinding dict.

    A binding with ``tiers`` is returned unchanged for downstream tier-selection.
    A binding with only ``default`` returns that string.  All other cases return ``None``.
    """
    if "tiers" in binding:
        return binding
    return binding.get("default")


def _apply_model_field(
    resolved_stage: dict[str, Any],
    default_model_map: dict[str, Any],
) -> None:
    """Resolve the ``model`` field on a stage dict in-place.

    When the stage has no ``model``, the provider-default binding is applied.
    When the stage carries an explicit ``modelBinding`` dict, it is normalized:
    a binding without ``tiers`` is collapsed to its ``default`` string; one with
    ``tiers`` is left unchanged for the downstream tier-selection step.
    """
    if "model" not in resolved_stage:
        resolved_provider: str | None = resolved_stage.get("provider")
        if resolved_provider is None:
            return
        provider_cfg: dict[str, Any] = default_model_map.get(resolved_provider) or {}
        model_value = _resolve_model_binding(provider_cfg)
        if model_value is None:
            return
        if isinstance(model_value, dict):
            resolved_stage["model"] = copy.deepcopy(model_value)
        else:
            resolved_stage["model"] = model_value
    elif isinstance(resolved_stage["model"], dict):
        model_value = _resolve_model_binding(resolved_stage["model"])
        if isinstance(model_value, str):
            resolved_stage["model"] = model_value
        # binding with tiers: preserve unchanged for downstream tier selection


def resolve_defaults(
    active_stages: list[dict[str, Any]],
    defaults_cfg: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Apply defaults.provider, defaults.backend, and defaults.model to each active stage.

    For each field:

    - ``provider``: if the stage has no ``provider`` key, apply
      ``defaults_cfg.get("provider")``.
    - ``backend``: if the stage has no ``backend`` key, apply
      ``defaults_cfg.get("backend")``.
    - ``model``: resolved via :func:`_apply_model_field` — see its docstring for the
      tiers-preservation rules.

    A stage that explicitly sets a field keeps its own value; this function never
    overrides a field the operator declared (even if its value is ``None``).

    After applying defaults, a stage without a non-empty ``provider`` raises
    ``ConfigError``.  The absence of ``backend`` is not an error here.

    This function is pure: it does not mutate the input list or any of its entries.
    It returns a new list of new dicts (deep-copied from the inputs).

    Args:
        active_stages: Stage dicts after profile expansion and disabled-stage filtering.
            Each entry must be a dict containing at minimum an ``id`` key.
        defaults_cfg: The ``defaults`` block from the operator config.  May be ``None``
            or empty; when absent, only stages that already carry all required fields
            are valid.

    Returns:
        A new list of new dicts with defaults applied.  Ordering matches the input.

    Raises:
        ConfigError: When a stage's ``provider`` field cannot be resolved after applying
            all available defaults.
    """
    if not defaults_cfg:
        defaults_cfg = {}

    default_provider: str | None = defaults_cfg.get("provider")
    default_backend: Any = defaults_cfg.get("backend")
    default_model_map: dict[str, Any] = defaults_cfg.get("models") or {}

    resolved_stages: list[dict[str, Any]] = []
    for stage in active_stages:
        resolved_stage = copy.deepcopy(stage)
        stage_id: str = resolved_stage.get("id", "<unknown>")

        if "provider" not in resolved_stage and default_provider is not None:
            resolved_stage["provider"] = default_provider

        if "backend" not in resolved_stage and default_backend is not None:
            resolved_stage["backend"] = default_backend

        _apply_model_field(resolved_stage, default_model_map)

        if not resolved_stage.get("provider"):
            raise ConfigError(
                f"stage '{stage_id}': required field 'provider' could not be resolved"
            )

        resolved_stages.append(resolved_stage)

    return resolved_stages
