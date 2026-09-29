"""Dogfood-config tests for normalize_config (issue #183).

Tests that the full normalization pipeline produces the exact NormalizedStage
values declared in the issue #183 acceptance criteria when run against the
.agentic/config.yml dogfood config.
"""
from __future__ import annotations

from pathlib import Path

_DOGFOOD_CONFIG_PATH = Path(__file__).resolve().parents[3] / ".agentic" / "config.yml"


def _load_dogfood_config() -> dict:
    """Return the parsed dogfood config dict from .agentic/config.yml."""
    import yaml  # type: ignore[import-untyped]

    with _DOGFOOD_CONFIG_PATH.open() as config_file:
        return yaml.safe_load(config_file)


def test_pipeline_dogfood_config_produces_two_stages() -> None:
    """The dogfood config declares exactly two stages, review and security → exactly 2 active."""
    from stagr.core.pipeline import normalize_config

    config = _load_dogfood_config()
    result = normalize_config(config)

    assert len(result) == 2, (
        f"Expected 2 NormalizedStage objects from dogfood config, got {len(result)}: "
        f"{[s.id for s in result]}"
    )


def test_pipeline_dogfood_config_stage_ids_present() -> None:
    """Active stage ids are exactly review and security."""
    from stagr.core.pipeline import normalize_config

    config = _load_dogfood_config()
    result = normalize_config(config)

    actual_ids = {stage.id for stage in result}
    expected_ids = {"review", "security"}
    assert actual_ids == expected_ids, (
        f"Expected stage ids {expected_ids}, got {actual_ids}"
    )


def test_pipeline_dogfood_config_review() -> None:
    """review stage has the exact field values from the acceptance criteria."""
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.pipeline import normalize_config

    config = _load_dogfood_config()
    result = normalize_config(config)

    matching = [s for s in result if s.id == "review"]
    assert matching, "Expected 'review' stage in pipeline output"
    stage = matching[0]

    assert stage.kind is StageKind.REVIEW, (
        f"review kind: expected REVIEW, got {stage.kind}"
    )
    assert stage.provider == "openai", (
        f"review provider: expected 'openai', got {stage.provider!r}"
    )
    assert stage.skill == "code-review", (
        f"review skill: expected 'code-review', got {stage.skill!r}"
    )
    assert stage.gate is StageGate.BLOCKING, (
        f"review gate: expected BLOCKING, got {stage.gate}"
    )
    assert stage.triggers == (StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED), (
        f"review triggers: expected (PR_OPENED, PR_UPDATED), got {stage.triggers}"
    )
    assert stage.dependencies == (), (
        f"review dependencies: expected (), got {stage.dependencies}"
    )


def test_pipeline_dogfood_config_security() -> None:
    """security stage has the exact field values from the acceptance criteria."""
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.pipeline import normalize_config

    config = _load_dogfood_config()
    result = normalize_config(config)

    matching = [s for s in result if s.id == "security"]
    assert matching, "Expected 'security' stage in pipeline output"
    stage = matching[0]

    assert stage.kind is StageKind.SECURITY, (
        f"security kind: expected SECURITY, got {stage.kind}"
    )
    assert stage.provider == "openai", (
        f"security provider: expected 'openai', got {stage.provider!r}"
    )
    assert stage.skill == "security-review", (
        f"security skill: expected 'security-review', got {stage.skill!r}"
    )
    assert stage.gate is StageGate.BLOCKING, (
        f"security gate: expected BLOCKING, got {stage.gate}"
    )
    assert stage.triggers == (StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED), (
        f"security triggers: expected (PR_OPENED, PR_UPDATED), got {stage.triggers}"
    )
    assert stage.dependencies == (), (
        f"security dependencies: expected (), got {stage.dependencies}"
    )


def test_pipeline_dogfood_config_no_enabled_field() -> None:
    """NormalizedStage objects have no 'enabled' attribute."""
    from stagr.core.pipeline import normalize_config

    config = _load_dogfood_config()
    result = normalize_config(config)

    for stage in result:
        assert not hasattr(stage, "enabled"), (
            f"NormalizedStage '{stage.id}' must not have an 'enabled' field"
        )


def test_pipeline_dogfood_config_backend_derived_from_provider() -> None:
    """Backend is derived from the provider default when not set per-stage in the dogfood config."""
    from stagr.core.pipeline import normalize_config
    from stagr.core.backend_names import BACKEND_CODEX

    config = _load_dogfood_config()
    result = normalize_config(config)

    stages_by_id = {s.id: s for s in result}

    review = stages_by_id["review"]
    assert review.backend == BACKEND_CODEX, (
        f"review backend: expected '{BACKEND_CODEX}', got {review.backend!r}"
    )

    security = stages_by_id["security"]
    assert security.backend == BACKEND_CODEX, (
        f"security backend: expected '{BACKEND_CODEX}', got {security.backend!r}"
    )
