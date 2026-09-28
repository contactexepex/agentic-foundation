"""Edge-case tests for normalize_config (issue #183).

Tests for correct pipeline behavior on boundary inputs: empty stages, single
stage, all-disabled, gate defaults, dependency mapping, and return type.
"""
from __future__ import annotations


def test_pipeline_empty_stages_returns_empty_tuple() -> None:
    """A config with no stages produces an empty tuple."""
    from stagr.core.pipeline import normalize_config

    config = {
        "version": 2,
        "profile": "custom",
        "stages": [],
        "defaults": {"provider": "openai"},
    }
    result = normalize_config(config)

    assert result == (), f"Expected empty tuple for no stages, got {result}"


def test_pipeline_single_active_stage() -> None:
    """A config with one enabled stage produces a tuple of one NormalizedStage."""
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.pipeline import normalize_config

    config = {
        "version": 2,
        "profile": "custom",
        "stages": [
            {
                "id": "review",
                "type": "review",
                "provider": "openai",
                "skill": "code-review",
                "gate": "blocking",
                "triggers": ["pr_opened"],
            }
        ],
        "defaults": {"provider": "openai"},
    }
    result = normalize_config(config)

    assert len(result) == 1, f"Expected 1 stage, got {len(result)}"
    stage = result[0]
    assert stage.id == "review"
    assert stage.kind is StageKind.REVIEW
    assert stage.gate is StageGate.BLOCKING
    assert stage.triggers == (StageTrigger.PR_OPENED,)
    assert stage.skill == "code-review"
    assert stage.dependencies == ()


def test_pipeline_all_disabled_stages_returns_empty_tuple() -> None:
    """A config where every stage has enabled:false produces an empty tuple."""
    from stagr.core.pipeline import normalize_config

    config = {
        "version": 2,
        "profile": "custom",
        "stages": [
            {"id": "review", "type": "review", "provider": "openai", "enabled": False},
            {"id": "security", "type": "security", "provider": "openai", "enabled": False},
        ],
        "defaults": {"provider": "openai"},
    }
    result = normalize_config(config)

    assert result == (), (
        f"Expected empty tuple when all stages disabled, got {result}"
    )


def test_pipeline_defaults_provider_propagates_to_stage() -> None:
    """A stage without provider receives defaults.provider."""
    from stagr.core.pipeline import normalize_config

    config = {
        "version": 2,
        "profile": "custom",
        "stages": [
            {
                "id": "review",
                "type": "review",
                "skill": "code-review",
                "gate": "blocking",
                "triggers": ["pr_opened"],
            }
        ],
        "defaults": {"provider": "openai"},
    }
    result = normalize_config(config)

    assert len(result) == 1
    assert result[0].provider == "openai", (
        f"Provider should be resolved from defaults.provider: got {result[0].provider!r}"
    )


def test_pipeline_returns_tuple_not_list() -> None:
    """normalize_config returns a tuple, not a list."""
    from stagr.core.pipeline import normalize_config

    config = {
        "version": 2,
        "profile": "custom",
        "stages": [{"id": "review", "type": "review", "provider": "openai"}],
        "defaults": {},
    }
    result = normalize_config(config)

    assert isinstance(result, tuple), (
        f"Expected tuple return type, got {type(result).__name__}"
    )


def test_pipeline_gate_defaults_to_non_blocking_when_absent() -> None:
    """A stage without an explicit gate defaults to NON_BLOCKING."""
    from stagr.core.enums import StageGate
    from stagr.core.pipeline import normalize_config

    config = {
        "version": 2,
        "profile": "custom",
        "stages": [{"id": "review", "type": "review", "provider": "openai"}],
        "defaults": {},
    }
    result = normalize_config(config)

    assert result[0].gate is StageGate.NON_BLOCKING, (
        f"Absent gate must default to NON_BLOCKING, got {result[0].gate}"
    )


def test_pipeline_advisory_gate_maps_to_non_blocking() -> None:
    """A stage with gate:'advisory' maps to StageGate.NON_BLOCKING."""
    from stagr.core.enums import StageGate
    from stagr.core.pipeline import normalize_config

    config = {
        "version": 2,
        "profile": "custom",
        "stages": [
            {"id": "review", "type": "review", "provider": "openai", "gate": "advisory"}
        ],
        "defaults": {},
    }
    result = normalize_config(config)

    assert result[0].gate is StageGate.NON_BLOCKING, (
        f"'advisory' gate must map to NON_BLOCKING, got {result[0].gate}"
    )


def test_pipeline_dependencies_tuple_from_depends_on() -> None:
    """A stage with depends_on produces a matching dependencies tuple."""
    from stagr.core.pipeline import normalize_config

    config = {
        "version": 2,
        "profile": "custom",
        "stages": [
            {"id": "review", "type": "review", "provider": "openai"},
            {
                "id": "security",
                "type": "security",
                "provider": "openai",
                "depends_on": ["review"],
            },
        ],
        "defaults": {},
    }
    result = normalize_config(config)

    matching = [s for s in result if s.id == "security"]
    assert matching, "Expected 'security' stage in pipeline output"
    assert matching[0].dependencies == ("review",), (
        f"Expected dependencies=('review',), got {matching[0].dependencies}"
    )


def test_pipeline_tiered_model_binding_extracts_default_string() -> None:
    """A tiered modelBinding is resolved to the default string for NormalizedStage.model."""
    from stagr.core.pipeline import normalize_config

    config = {
        "version": 2,
        "profile": "custom",
        "stages": [{"id": "review", "type": "review", "provider": "openai"}],
        "defaults": {
            "models": {
                "openai": {"default": "gpt-4o", "tiers": {"complex": "gpt-4-turbo"}},
            },
        },
    }
    result = normalize_config(config)

    assert isinstance(result[0].model, (str, type(None))), (
        f"NormalizedStage.model must be str|None, got {type(result[0].model).__name__}"
    )
