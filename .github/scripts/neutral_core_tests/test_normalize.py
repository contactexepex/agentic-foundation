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
    """The implement-codex stage (enabled: false) is excluded from the dogfood config."""
    from pathlib import Path

    from neutral_core_tests.harness import REPO_ROOT

    config_path = Path(REPO_ROOT) / ".agentic" / "config.yml"

    import yaml  # noqa: PLC0415 — available in the CI environment

    with config_path.open() as config_file:
        raw_cfg = yaml.safe_load(config_file)

    from stagr.core.normalize import filter_disabled_stages

    raw_stages = raw_cfg.get("stages", []) or []
    enabled_stages = filter_disabled_stages(raw_stages)

    enabled_ids = {stage["id"] for stage in enabled_stages}
    assert "implement-codex" not in enabled_ids, (
        "implement-codex has enabled: false and must be excluded"
    )
    # Sanity: the enabled stages are still present.
    assert "implement-claude" in enabled_ids
    assert "review" in enabled_ids
