"""Tests for normalize.py — profile expansion (issue #180)."""
from __future__ import annotations


def test_expand_profile_defaults_standard_fills_missing_fields() -> None:
    """standard profile fills provider and gate into a stage with only id and type."""
    from stagr.core.normalize import expand_profile_defaults

    minimal_stage = {"id": "review", "type": "review"}
    result = expand_profile_defaults("standard", [minimal_stage])

    review_stage = next(s for s in result if s["id"] == "review")
    assert review_stage.get("provider") == "openai", (
        f"Expected provider 'openai', got {review_stage.get('provider')}"
    )
    assert review_stage.get("gate") == "blocking", (
        f"Expected gate 'blocking', got {review_stage.get('gate')}"
    )


def test_expand_profile_defaults_custom_adds_no_fields() -> None:
    """custom profile is the identity: no fields are added and no stages injected."""
    from stagr.core.normalize import expand_profile_defaults

    minimal_stage = {"id": "review", "type": "review"}
    result = expand_profile_defaults("custom", [minimal_stage])

    assert len(result) == 1, f"custom must not add stages: got {[s['id'] for s in result]}"
    assert result[0] == {"id": "review", "type": "review"}, (
        f"custom profile must not add fields: got {result[0]}"
    )


def test_expand_profile_defaults_explicit_fields_override_profile() -> None:
    """Operator-declared fields take precedence over profile defaults."""
    from stagr.core.normalize import expand_profile_defaults

    # Operator pins gate to advisory; standard defaults would set it to blocking.
    stage_with_override = {"id": "review", "type": "review", "gate": "advisory"}
    result = expand_profile_defaults("standard", [stage_with_override])

    review_stage = next(s for s in result if s["id"] == "review")
    assert review_stage["gate"] == "advisory", (
        f"Operator gate must override profile default: got {review_stage['gate']}"
    )
    # Provider from the profile is still applied (operator did not override it).
    assert review_stage.get("provider") == "openai", (
        f"Profile provider default must be present when not overridden: "
        f"got {review_stage.get('provider')}"
    )


def test_expand_profile_defaults_unrecognized_profile_raises() -> None:
    """An unrecognized profile name raises ValueError referencing V-S01."""
    from stagr.core.normalize import expand_profile_defaults

    raised = False
    try:
        expand_profile_defaults("nonexistent-profile", [])
    except ValueError as exc:
        raised = True
        assert "V-S01" in str(exc), f"Error must reference V-S01: {exc}"
    assert raised, "Expected ValueError for an unrecognized profile name"


def test_expand_profile_defaults_is_idempotent() -> None:
    """Applying expand_profile_defaults twice produces the same result."""
    from stagr.core.normalize import expand_profile_defaults

    stage = {"id": "review", "type": "review"}
    first_pass = expand_profile_defaults("standard", [stage])
    second_pass = expand_profile_defaults("standard", first_pass)

    first_ids = [s["id"] for s in first_pass]
    second_ids = [s["id"] for s in second_pass]
    assert first_ids == second_ids, (
        f"Stage ordering not preserved across two passes: {first_ids} vs {second_ids}"
    )
    review_first = next(s for s in first_pass if s["id"] == "review")
    review_second = next(s for s in second_pass if s["id"] == "review")
    assert review_first == review_second, (
        f"Not idempotent for review stage: {review_first} != {review_second}"
    )


def test_expand_profile_defaults_does_not_mutate_input() -> None:
    """The explicit_stages list and its entries are never mutated."""
    from stagr.core.normalize import expand_profile_defaults

    original_stage = {"id": "review", "type": "review"}
    original_list = [original_stage]
    expand_profile_defaults("standard", original_list)

    assert original_stage == {"id": "review", "type": "review"}, (
        f"Input stage dict was mutated: {original_stage}"
    )
    assert len(original_list) == 1, "Input list length was changed"


def test_expand_profile_defaults_standard_includes_all_profile_stages() -> None:
    """standard profile stages are present in the output even when not explicitly declared."""
    from stagr.core.normalize import expand_profile_defaults

    # Explicit list has only one stage; standard also defines implement and review.
    result = expand_profile_defaults("standard", [{"id": "security", "type": "security"}])
    output_ids = [s["id"] for s in result]

    assert "implement" in output_ids, "standard profile 'implement' stage must be in output"
    assert "review" in output_ids, "standard profile 'review' stage must be in output"
    assert "security" in output_ids, "explicitly declared 'security' stage must be in output"
