"""V-S11 static validation tests.

V-S11: fast_path.enabled: false with routing keys present emits a dormant-routing warning.

Key membership (key present in dict) — not truthiness — determines whether a routing
key is "present".  Explicitly-retained empty values (globs: [], stages: {}) still
trigger the warning because the key is present.
"""
from __future__ import annotations

import warnings

from stagr.render.config import _warn_dormant_routing_config


def _dormant_routing_warning_emitted() -> bool:
    """Returns True when _warn_dormant_routing_config emits a UserWarning."""
    cfg = {
        "routing": {
            "fast_path": {
                "enabled": False,
                "globs": ["*.md", "docs/**"],
            }
        }
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return any(
        issubclass(w.category, UserWarning) and "dormant" in str(w.message).lower()
        for w in caught
    )


def _dormant_routing_stages_warning_emitted() -> bool:
    """routing.fast_path.stages present also triggers the dormant warning."""
    cfg = {
        "routing": {
            "fast_path": {
                "enabled": False,
                "stages": ["implement"],
            }
        }
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return any(
        issubclass(w.category, UserWarning) and "dormant" in str(w.message).lower()
        for w in caught
    )


def _no_dormant_routing_warning_when_fast_path_enabled() -> bool:
    """No warning emitted when fast_path.enabled: true, even with globs."""
    cfg = {
        "routing": {
            "fast_path": {
                "enabled": True,
                "globs": ["*.md"],
            }
        }
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return not any(issubclass(w.category, UserWarning) for w in caught)


def _no_dormant_routing_warning_when_no_routing_keys() -> bool:
    """No warning when fast_path is disabled but no routing keys are set."""
    cfg = {"routing": {"fast_path": {"enabled": False}}}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return not any(issubclass(w.category, UserWarning) for w in caught)


def _dormant_routing_warning_on_empty_globs_list() -> bool:
    """globs: [] (key present but empty) must still trigger the dormant warning.

    Regression test for the key-presence check: an empty list is falsy but the
    KEY is present, so the warning must fire.
    """
    cfg = {
        "routing": {
            "fast_path": {
                "enabled": False,
                "globs": [],
            }
        }
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return any(
        issubclass(w.category, UserWarning) and "dormant" in str(w.message).lower()
        for w in caught
    )


def _dormant_routing_warning_on_empty_stages_dict() -> bool:
    """stages: {} (key present but empty) must still trigger the dormant warning.

    Regression test for the key-presence check: an empty dict is falsy but the
    KEY is present, so the warning must fire.
    """
    cfg = {
        "routing": {
            "fast_path": {
                "enabled": False,
                "stages": {},
            }
        }
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return any(
        issubclass(w.category, UserWarning) and "dormant" in str(w.message).lower()
        for w in caught
    )
