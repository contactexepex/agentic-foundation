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


def test_pipeline_dogfood_config_produces_three_stages() -> None:
    """The dogfood config has 4 declared stages; 1 is disabled → exactly 3 active."""
    from stagr.core.pipeline import normalize_config

    config = _load_dogfood_config()
    result = normalize_config(config)

    assert len(result) == 3, (
        f"Expected 3 NormalizedStage objects from dogfood config, got {len(result)}: "
        f"{[s.id for s in result]}"
    )


def test_pipeline_dogfood_config_stage_ids_present() -> None:
    """Active stage ids include implement-claude, review, and security."""
    from stagr.core.pipeline import normalize_config

    config = _load_dogfood_config()
    result = normalize_config(config)

    actual_ids = {stage.id for stage in result}
    expected_ids = {"implement-claude", "review", "security"}
    assert actual_ids == expected_ids, (
        f"Expected stage ids {expected_ids}, got {actual_ids}"
    )


def test_pipeline_dogfood_config_implement_claude() -> None:
    """implement-claude stage has the exact field values from the acceptance criteria."""
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.pipeline import normalize_config

    config = _load_dogfood_config()
    result = normalize_config(config)

    matching = [s for s in result if s.id == "implement-claude"]
    assert matching, "Expected 'implement-claude' stage in pipeline output"
    stage = matching[0]

    assert stage.kind is StageKind.IMPLEMENT, (
        f"implement-claude kind: expected IMPLEMENT, got {stage.kind}"
    )
    assert stage.provider == "anthropic", (
        f"implement-claude provider: expected 'anthropic', got {stage.provider!r}"
    )
    assert stage.skill is None, (
        f"implement-claude skill: expected None, got {stage.skill!r}"
    )
    assert stage.gate is StageGate.NON_BLOCKING, (
        f"implement-claude gate: expected NON_BLOCKING, got {stage.gate}"
    )
    assert stage.triggers == (StageTrigger.MANUAL,), (
        f"implement-claude triggers: expected (MANUAL,), got {stage.triggers}"
    )
    assert stage.dependencies == (), (
        f"implement-claude dependencies: expected (), got {stage.dependencies}"
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
    """Backend is derived from PROVIDER_TOOL when not set per-stage in the dogfood config."""
    from stagr.core.pipeline import normalize_config
    from stagr.render.constants import BACKEND_CLAUDE_ACTION, BACKEND_CODEX

    config = _load_dogfood_config()
    result = normalize_config(config)

    stages_by_id = {s.id: s for s in result}

    implement_claude = stages_by_id["implement-claude"]
    assert implement_claude.backend == BACKEND_CLAUDE_ACTION, (
        f"implement-claude backend: expected '{BACKEND_CLAUDE_ACTION}', "
        f"got {implement_claude.backend!r}"
    )

    review = stages_by_id["review"]
    assert review.backend == BACKEND_CODEX, (
        f"review backend: expected '{BACKEND_CODEX}', got {review.backend!r}"
    )

    security = stages_by_id["security"]
    assert security.backend == BACKEND_CODEX, (
        f"security backend: expected '{BACKEND_CODEX}', got {security.backend!r}"
    )
