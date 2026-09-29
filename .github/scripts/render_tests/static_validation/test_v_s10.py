"""V-S10 static validation tests.

V-S10: modules.auto_merge: true requires at least one BLOCKING stage.
"""
from __future__ import annotations

from render_tests.harness import render
from render_tests.static_validation._common import _base_cfg


def _v_s10_auto_merge_no_blocking() -> None:
    """auto_merge: true with only advisory stages must raise V-S10 RenderError."""
    cfg = _base_cfg(
        modules={"auto_merge": True},
        stages=[
            {
                "id": "implement",
                "type": "implement",
                "provider": "anthropic",
                "gate": "advisory",
            }
        ],
    )
    render.validate_config(cfg)


def _v_s10_auto_merge_with_blocking() -> None:
    """auto_merge: true with a BLOCKING Codex review stage must NOT raise."""
    # Only Codex review/security stages contribute to the auto-merge gate (check (a)),
    # so use a blocking Codex review stage (with pr_updated trigger) to satisfy V-S10.
    cfg = {
        "version": 2,
        "profile": "custom",
        "platform": {"type": "github", "default_branch": "main"},
        "defaults": {"provider": "openai", "models": {}},
        "modules": {"auto_merge": True},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [
            {
                "id": "review",
                "type": "review",
                "backend": {"name": "codex"},
                "gate": "blocking",
                "triggers": ["pr_opened", "pr_updated"],
            }
        ],
    }
    render.validate_config(cfg)


def _v_s10_no_auto_merge_no_blocking() -> None:
    """No auto_merge flag with only advisory stages is fine — V-S10 is silent."""
    cfg = _base_cfg(
        stages=[
            {
                "id": "implement",
                "type": "implement",
                "provider": "anthropic",
                "gate": "advisory",
            }
        ],
    )
    render.validate_config(cfg)
