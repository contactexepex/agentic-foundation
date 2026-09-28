"""Policy derivation for the neutral-core normalization pipeline.

Implements Group C derivation functions (issues #184–#187). Each function
accepts the parsed config dict and returns the corresponding frozen policy
dataclass. Only ``derive_routing_policy`` is implemented here (#185); the
remaining Group C functions (#184, #186, #187) will be added as their
respective issues land.
"""
from __future__ import annotations

from typing import Any

from .models import FastPathPolicy, PathMatchSpec, RouteStageMap, RoutingPolicy


def derive_routing_policy(config: dict[str, Any]) -> RoutingPolicy:
    """Derive a ``RoutingPolicy`` from the parsed config dict.

    Reads ``routing.fast_path`` to determine whether fast-path routing is
    active and, when it is, extracts the glob match patterns and route-stage
    map.

    Derivation rules
    ----------------
    - When ``routing`` is absent -> ``RoutingPolicy(fast_path=None)``
    - When ``routing.fast_path.enabled`` is ``false`` -> ``RoutingPolicy(fast_path=None)``
    - When ``routing.fast_path.enabled`` is ``true`` -> ``RoutingPolicy`` with a
      fully-populated ``FastPathPolicy`` (``match`` glob patterns and ``stages``
      route-stage map).

    V-S09 (route dependency-closure) is NOT validated here; it belongs in a
    separate validation pass.

    Parameters
    ----------
    config:
        The raw YAML config dict (top-level, as loaded by ``yaml.safe_load``).

    Returns
    -------
    RoutingPolicy
        An immutable routing-policy dataclass. ``fast_path`` is ``None`` when
        fast-path is disabled or the ``routing`` key is absent.
    """
    routing_cfg: dict[str, Any] = config.get("routing") or {}
    if not routing_cfg:
        return RoutingPolicy(fast_path=None)

    fast_path_cfg: dict[str, Any] = routing_cfg.get("fast_path") or {}
    if not fast_path_cfg.get("enabled", False):
        return RoutingPolicy(fast_path=None)

    match_paths: tuple[str, ...] = tuple(
        fast_path_cfg.get("match", {}).get("paths", [])
    )
    stages_cfg: dict[str, Any] = fast_path_cfg.get("stages") or {}
    fast_stage_ids: tuple[str, ...] = tuple(stages_cfg.get("fast", []))
    normal_stage_ids: tuple[str, ...] = tuple(stages_cfg.get("normal", []))

    fast_path = FastPathPolicy(
        match=PathMatchSpec(paths=match_paths),
        stages=RouteStageMap(fast=fast_stage_ids, normal=normal_stage_ids),
    )
    return RoutingPolicy(fast_path=fast_path)
