"""Tests for derive_routing_policy (issue #185).

Covers all acceptance criteria:
- Absent ``routing`` key → ``RoutingPolicy(fast_path=None)``
- ``fast_path.enabled: false`` → ``RoutingPolicy(fast_path=None)``
- ``fast_path.enabled: true`` → fully-populated ``FastPathPolicy``
- Dogfood config (``fast_path.enabled: false``) → ``RoutingPolicy(fast_path=None)``
- Dormant routing config (keys present but ``enabled: false``) → no error
"""
from __future__ import annotations

from pathlib import Path

_DOGFOOD_CONFIG_PATH = Path(__file__).resolve().parents[3] / ".agentic" / "config.yml"


def _load_dogfood_config() -> dict:
    """Return the parsed dogfood config dict from .agentic/config.yml."""
    import yaml  # type: ignore[import-untyped]

    with _DOGFOOD_CONFIG_PATH.open() as config_file:
        return yaml.safe_load(config_file)


def test_routing_policy_dogfood_config() -> None:
    """Dogfood config (fast_path.enabled: false) → RoutingPolicy(fast_path=None)."""
    from stagr.core.policy import derive_routing_policy

    config = _load_dogfood_config()
    result = derive_routing_policy(config)

    assert result.fast_path is None, (
        f"Dogfood config has fast_path.enabled: false; expected fast_path=None, "
        f"got {result.fast_path!r}"
    )


def test_routing_policy_absent_routing_key() -> None:
    """Config with no 'routing' key → fast_path is None."""
    from stagr.core.policy import derive_routing_policy

    result = derive_routing_policy({})

    assert result.fast_path is None, (
        f"Config with no 'routing' key: expected fast_path=None, got {result.fast_path!r}"
    )


def test_routing_policy_disabled_fast_path() -> None:
    """fast_path.enabled: false → fast_path is None."""
    from stagr.core.policy import derive_routing_policy

    config = {"routing": {"fast_path": {"enabled": False}}}
    result = derive_routing_policy(config)

    assert result.fast_path is None, (
        f"fast_path.enabled=False: expected fast_path=None, got {result.fast_path!r}"
    )


def test_routing_policy_enabled_fast_path() -> None:
    """fast_path.enabled: true with two glob patterns → fast_path populated."""
    from stagr.core.models import FastPathPolicy, PathMatchSpec, RouteStageMap
    from stagr.core.policy import derive_routing_policy

    config = {
        "routing": {
            "fast_path": {
                "enabled": True,
                "match": {"paths": ["docs/**", "*.md"]},
                "stages": {
                    "fast": ["review"],
                    "normal": ["review", "security"],
                },
            }
        }
    }
    result = derive_routing_policy(config)

    assert result.fast_path is not None, "expected fast_path to be populated when enabled: true"
    assert isinstance(result.fast_path, FastPathPolicy), (
        f"expected FastPathPolicy, got {type(result.fast_path)}"
    )
    assert isinstance(result.fast_path.match, PathMatchSpec), (
        f"expected PathMatchSpec, got {type(result.fast_path.match)}"
    )
    assert isinstance(result.fast_path.stages, RouteStageMap), (
        f"expected RouteStageMap, got {type(result.fast_path.stages)}"
    )
    assert "docs/**" in result.fast_path.match.paths, (
        f"expected 'docs/**' in match.paths, got {result.fast_path.match.paths!r}"
    )
    assert "*.md" in result.fast_path.match.paths, (
        f"expected '*.md' in match.paths, got {result.fast_path.match.paths!r}"
    )
    assert result.fast_path.stages.fast == ("review",), (
        f"expected fast stages ('review',), got {result.fast_path.stages.fast!r}"
    )
    assert result.fast_path.stages.normal == ("review", "security"), (
        f"expected normal stages ('review', 'security'), got {result.fast_path.stages.normal!r}"
    )


def test_routing_policy_no_error_on_dormant_config() -> None:
    """Routing keys present but enabled: false → no error, fast_path is None."""
    from stagr.core.policy import derive_routing_policy

    config = {
        "routing": {
            "fast_path": {
                "enabled": False,
                "match": {"paths": ["docs/**"]},
                "stages": {
                    "fast": ["review"],
                    "normal": ["review", "security"],
                },
            }
        }
    }
    result = derive_routing_policy(config)

    assert result.fast_path is None, (
        f"Dormant config (enabled=False with populated keys): "
        f"expected fast_path=None, got {result.fast_path!r}"
    )


def test_routing_policy_routing_present_no_fast_path_key() -> None:
    """Routing section present but fast_path sub-key absent → fast_path is None."""
    from stagr.core.policy import derive_routing_policy

    result = derive_routing_policy({"routing": {}})

    assert result.fast_path is None, (
        f"routing present but no fast_path key: expected fast_path=None, "
        f"got {result.fast_path!r}"
    )
