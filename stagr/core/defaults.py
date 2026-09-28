"""Backend and model default resolution for the neutral-core normalization pipeline.

Implements the third step of the normalization pipeline (issue #181): after profile
expansion and disabled-stage filtering, each active stage's ``provider``, ``backend``,
and ``model`` fields are resolved against ``defaults`` from the operator config.

**Resolution order:**

1. ``provider``: if the stage has no ``provider`` key, apply ``defaults.provider``.
2. ``backend``: if the stage has no ``backend`` key, apply ``defaults.backend`` (when present).
3. ``model``: if the stage has no ``model`` key, look up
   ``defaults.models[resolved_provider].default`` and apply it when found.

After resolution, every stage must have a non-empty ``provider``; stages that still lack
one raise ``ConfigError``.  The absence of ``backend`` after defaults resolution is **not**
an error at this layer — per-provider backend defaults are registered in the
BackendRenderer registry and applied in a later normalization step.

**Vocabulary layer:** operates in the raw M1 config vocabulary (``depends_on``, not
``dependencies``; string literals for gate values, not enum instances).

Design source: design-docs/03-provider-backend-model.md
"""
from __future__ import annotations

import copy
from typing import Any

from .models import ConfigError


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
    - ``model``: if the stage has no ``model`` key and the resolved provider is known,
      look up ``defaults_cfg["models"][resolved_provider]["default"]`` and apply it when
      found; otherwise leave ``model`` absent.

    A stage that explicitly sets a field keeps its own value; this function never
    overrides a field the operator declared (even if its value is ``None``).

    After applying defaults, a stage without a non-empty ``provider`` raises
    ``ConfigError``.  The absence of ``backend`` is not an error here — it is resolved
    by the BackendRenderer registry in a later step.

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

        resolved_provider: str | None = resolved_stage.get("provider")
        if "model" not in resolved_stage and resolved_provider is not None:
            provider_model_cfg: dict[str, Any] = default_model_map.get(resolved_provider) or {}
            model_default: str | None = provider_model_cfg.get("default")
            if model_default is not None:
                resolved_stage["model"] = model_default

        if not resolved_stage.get("provider"):
            raise ConfigError(
                f"stage '{stage_id}': required field 'provider' could not be resolved"
            )

        resolved_stages.append(resolved_stage)

    return resolved_stages
