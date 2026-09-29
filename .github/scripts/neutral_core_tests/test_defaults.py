"""Tests for resolve_defaults (issue #181) — backend and model default resolution."""
from __future__ import annotations


def test_defaults_provider_propagates() -> None:
    """A stage omitting provider receives the defaults.provider value."""
    from stagr.core.defaults import resolve_defaults

    active_stages = [{"id": "review", "type": "review"}]
    defaults_cfg = {"provider": "openai"}
    result = resolve_defaults(active_stages, defaults_cfg)

    assert len(result) == 1
    assert result[0]["provider"] == "openai", (
        f"Expected provider='openai', got {result[0].get('provider')}"
    )


def test_defaults_explicit_provider_not_overridden() -> None:
    """A stage with an explicit provider keeps its own value; defaults.provider does not override it."""
    from stagr.core.defaults import resolve_defaults

    active_stages = [{"id": "review", "type": "review", "provider": "openai"}]
    defaults_cfg = {"provider": "anthropic"}
    result = resolve_defaults(active_stages, defaults_cfg)

    assert result[0]["provider"] == "openai", (
        f"Explicit provider must not be overridden by defaults: got {result[0].get('provider')}"
    )


def test_defaults_model_resolved_from_defaults() -> None:
    """A stage omitting model receives defaults.models[resolved_provider].default."""
    from stagr.core.defaults import resolve_defaults

    active_stages = [{"id": "implement-claude", "type": "implement", "provider": "anthropic"}]
    defaults_cfg = {
        "provider": "anthropic",
        "models": {
            "anthropic": {"default": "claude-sonnet-5"},
        },
    }
    result = resolve_defaults(active_stages, defaults_cfg)

    assert result[0].get("model") == "claude-sonnet-5", (
        f"Model must be resolved from defaults.models.anthropic.default: "
        f"got {result[0].get('model')}"
    )


def test_defaults_model_absent_when_no_provider_default() -> None:
    """A stage whose resolved provider has no model default keeps model absent."""
    from stagr.core.defaults import resolve_defaults

    active_stages = [{"id": "review", "type": "review", "provider": "openai"}]
    defaults_cfg = {
        "models": {
            "anthropic": {"default": "claude-sonnet-5"},
        },
    }
    result = resolve_defaults(active_stages, defaults_cfg)

    assert "model" not in result[0], (
        f"Model must remain absent when provider has no model default: got {result[0]}"
    )


def test_defaults_missing_provider_raises_config_error() -> None:
    """A stage with no provider and no defaults.provider raises ConfigError."""
    from stagr.core.defaults import resolve_defaults
    from stagr.core.models import ConfigError

    active_stages = [{"id": "review", "type": "review"}]
    defaults_cfg: dict = {}

    raised = False
    try:
        resolve_defaults(active_stages, defaults_cfg)
    except ConfigError as exc:
        raised = True
        assert "review" in str(exc), f"ConfigError must name the stage id: {exc}"
        assert "provider" in str(exc).lower(), f"ConfigError must mention 'provider': {exc}"
    assert raised, "Expected ConfigError when provider cannot be resolved"


def test_defaults_does_not_mutate_input() -> None:
    """Input stage dicts are not mutated by resolve_defaults."""
    from stagr.core.defaults import resolve_defaults

    original_stage = {"id": "review", "type": "review"}
    original_list = [original_stage]
    defaults_cfg = {"provider": "openai"}

    resolve_defaults(original_list, defaults_cfg)

    assert "provider" not in original_stage, (
        f"Input stage dict was mutated: {original_stage}"
    )
    assert len(original_list) == 1, "Input list length was changed"
    assert original_stage == {"id": "review", "type": "review"}, (
        f"Input stage dict contents were changed: {original_stage}"
    )


def test_defaults_empty_defaults_cfg() -> None:
    """Empty or None defaults_cfg works without error when stages already carry required fields."""
    from stagr.core.defaults import resolve_defaults

    fully_specified_stage = {"id": "review", "type": "review", "provider": "openai"}

    result_empty_dict = resolve_defaults([fully_specified_stage], {})
    assert result_empty_dict[0]["provider"] == "openai", (
        f"Provider must be preserved with empty defaults_cfg: "
        f"got {result_empty_dict[0].get('provider')}"
    )

    result_none_cfg = resolve_defaults([fully_specified_stage], None)
    assert result_none_cfg[0]["provider"] == "openai", (
        f"Provider must be preserved with None defaults_cfg: "
        f"got {result_none_cfg[0].get('provider')}"
    )


def test_defaults_explicit_model_binding_normalized_to_string() -> None:
    """An explicit modelBinding object on a stage is normalized to its default string.

    The config schema defines stage.model as a modelBinding object.  resolve_defaults
    must normalize it to a plain string so all code paths produce a consistent
    str | None representation for NormalizedStage.model.
    """
    from stagr.core.defaults import resolve_defaults

    active_stages = [
        {
            "id": "review",
            "type": "review",
            "provider": "openai",
            "model": {"default": "gpt-4o"},
        }
    ]
    result = resolve_defaults(active_stages, {})

    assert result[0]["model"] == "gpt-4o", (
        f"modelBinding must be normalized to its default string: got {result[0].get('model')}"
    )


def test_defaults_provider_binding_applies_its_default_string() -> None:
    """A provider binding in defaults.models supplies its ``default`` string to the stage."""
    from stagr.core.defaults import resolve_defaults

    active_stages = [{"id": "review", "type": "review", "provider": "openai"}]
    result = resolve_defaults(active_stages, {"models": {"openai": {"default": "gpt-base"}}})

    assert result[0]["model"] == "gpt-base", (
        f"Provider binding must apply its default string: got {result[0].get('model')}"
    )


def test_defaults_binding_without_default_is_left_unchanged() -> None:
    """A stage modelBinding with no ``default`` key is left as it is; nothing invents a model."""
    from stagr.core.defaults import resolve_defaults

    empty_binding: dict = {}
    active_stages = [{"id": "review", "type": "review", "provider": "openai", "model": empty_binding}]
    result = resolve_defaults(active_stages, {})

    assert result[0]["model"] == empty_binding, (
        f"A binding without default must be preserved unchanged: got {result[0].get('model')}"
    )
