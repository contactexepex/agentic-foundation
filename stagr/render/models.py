"""Provider/model resolution: pick a stage's model per tier (most-specific-first, fail loud)
and derive a stage's effective backend name."""
from __future__ import annotations

from typing import Any

from .constants import BACKEND_GENERIC
from .errors import RenderError


def _model_for_tier(binding: dict[str, Any] | None, tier: str) -> str | None:
    """Pick a model id from a `{tiers: {...}, default: ...}` binding for `tier`, else None."""
    if not binding:
        return None
    tiers = binding.get("tiers") or {}
    return tiers.get(tier) or binding.get("default")


def resolve_model(
    cfg: dict[str, Any],
    stage: dict[str, Any],
    tier: str = "standard",
    request_override: str | None = None,
) -> str:
    """Resolve a stage's model for a tier, most-specific-first, then fail loud."""
    provider = stage.get("provider") or (cfg.get("defaults", {}) or {}).get("provider")
    if not provider:
        raise RenderError(
            f"stage '{stage.get('id')}' has no provider and defaults.provider is unset"
        )
    value = (
        request_override
        or _model_for_tier(stage.get("model"), tier)
        or _model_for_tier((cfg.get("defaults", {}).get("models", {}) or {}).get(provider), tier)
    )
    if not value:
        raise RenderError(
            f"no model resolves for stage '{stage.get('id')}' (provider '{provider}', tier "
            f"'{tier}'): set stages[].model or defaults.models.{provider}.default"
        )
    aliases = (cfg.get("models", {}) or {}).get("aliases", {}) or {}
    if value in aliases:
        mapped = aliases[value].get(provider)
        if not mapped:
            raise RenderError(
                f"alias '{value}' has no mapping for provider '{provider}' "
                f"(stage '{stage.get('id')}')"
            )
        return mapped
    return value


def _stage_backend(stage: dict[str, Any]) -> str:
    return ((stage.get("backend") or {}).get("name")) or BACKEND_GENERIC
