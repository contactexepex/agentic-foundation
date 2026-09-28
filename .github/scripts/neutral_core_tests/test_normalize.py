"""Tests for the enabled-flag pre-processing step (issue #179)."""
from __future__ import annotations


def test_filter_disabled_stages_removes_disabled() -> None:
    """A stage with enabled: false is absent from the filtered output."""
    from stagr.core.normalize import filter_disabled_stages

    raw_stages = [
        {"id": "disabled-stage", "enabled": False},
        {"id": "enabled-stage", "enabled": True},
    ]
    result = filter_disabled_stages(raw_stages)
    assert len(result) == 1, f"Expected 1 stage, got {len(result)}"
    assert result[0]["id"] == "enabled-stage"


def test_filter_disabled_stages_absent_defaults_to_enabled() -> None:
    """A stage with no enabled field defaults to enabled and is present."""
    from stagr.core.normalize import filter_disabled_stages

    raw_stages = [
        {"id": "no-enabled-key"},
        {"id": "explicit-false", "enabled": False},
    ]
    result = filter_disabled_stages(raw_stages)
    assert len(result) == 1, f"Expected 1 stage, got {len(result)}"
    assert result[0]["id"] == "no-enabled-key"


def test_filter_disabled_stages_explicit_true_is_present() -> None:
    """A stage with enabled: true is present in the filtered output."""
    from stagr.core.normalize import filter_disabled_stages

    raw_stages = [{"id": "explicit-true", "enabled": True}]
    result = filter_disabled_stages(raw_stages)
    assert len(result) == 1
    assert result[0]["id"] == "explicit-true"


def test_filter_disabled_stages_does_not_mutate_input() -> None:
    """The original stage list and its entries are not mutated."""
    from stagr.core.normalize import filter_disabled_stages

    original_stage = {"id": "a-stage", "enabled": False}
    raw_stages = [original_stage]
    result = filter_disabled_stages(raw_stages)
    assert result == [], f"Expected empty result, got {result}"
    # The original dict and list must be untouched.
    assert original_stage == {"id": "a-stage", "enabled": False}
    assert len(raw_stages) == 1


def test_filter_disabled_stages_dogfood_config() -> None:
    """The implement-codex stage (enabled: false) is excluded from the dogfood config.

    This test exercises the real pipeline entry point (``expand_stages``) rather
    than calling ``filter_disabled_stages`` directly, so it validates the actual
    call path used at render time: profile expansion → merge → disabled-stage
    removal → backend defaults.
    """
    from pathlib import Path

    from neutral_core_tests.harness import REPO_ROOT

    config_path = Path(REPO_ROOT) / ".agentic" / "config.yml"

    import yaml  # noqa: PLC0415 — available in the CI environment

    with config_path.open() as config_file:
        raw_cfg = yaml.safe_load(config_file)

    from stagr.render.stages import expand_stages

    active_stages = expand_stages(raw_cfg)

    active_ids = {stage["id"] for stage in active_stages}
    assert "implement-codex" not in active_ids, (
        "implement-codex has enabled: false and must be excluded from the active stage set"
    )
    # Sanity: the enabled stages are still present.
    assert "implement-claude" in active_ids
    assert "review" in active_ids


def test_filter_disabled_stages_disables_profile_provided_stage() -> None:
    """An operator enabled:false override correctly suppresses a profile-provided stage.

    The standard profile includes a ``security`` stage.  When the operator config
    adds ``{id: security, enabled: false}``, the merged entry has ``enabled: false``
    and ``filter_disabled_stages`` (called inside ``expand_stages`` after merging)
    must exclude it.  This demonstrates Option B semantics: filtering runs AFTER
    profile expansion and override merging, so the operator can suppress any
    profile-provided stage by id.
    """
    from stagr.render.stages import expand_stages

    cfg: dict = {
        "profile": "standard",
        "stages": [
            {"id": "security", "enabled": False},
        ],
    }
    active_stages = expand_stages(cfg)

    active_ids = {stage["id"] for stage in active_stages}
    assert "security" not in active_ids, (
        "security stage has enabled: false after operator override merge and must be excluded"
    )
    # The other standard profile stages (implement, review) must still be present.
    assert "implement" in active_ids
    assert "review" in active_ids
