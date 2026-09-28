"""Tests for normalize.py — disabled-stage filtering (issue #179) and profile expansion (issue #180)."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# filter_disabled_stages (issue #179)
# ---------------------------------------------------------------------------

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
    assert "implement-claude" in active_ids
    assert "review" in active_ids


def test_filter_disabled_stages_disables_profile_provided_stage() -> None:
    """An operator enabled:false override correctly suppresses a profile-provided stage.

    The render-layer standard profile includes a ``security`` stage.  When the
    operator config adds ``{id: security, type: security, enabled: false}``, the
    merged entry has ``enabled: false`` and ``filter_disabled_stages`` (called
    inside ``expand_stages`` after merging) must exclude it.  This demonstrates
    Option B semantics: filtering runs AFTER profile expansion and override
    merging, so the operator can suppress any profile-provided stage by id.
    """
    from stagr.render.stages import expand_stages

    cfg: dict = {
        "profile": "standard",
        "stages": [
            {"id": "security", "type": "security", "enabled": False},
        ],
    }
    active_stages = expand_stages(cfg)

    active_ids = {stage["id"] for stage in active_stages}
    assert "security" not in active_ids, (
        "security stage has enabled: false after operator override merge and must be excluded"
    )
    assert "implement" in active_ids
    assert "review" in active_ids


# ---------------------------------------------------------------------------
# expand_profile_defaults (issue #180)
# ---------------------------------------------------------------------------

def test_expand_profile_defaults_minimal_shape() -> None:
    """minimal profile expands to exactly one BLOCKING review stage with all required fields."""
    from stagr.core.normalize import expand_profile_defaults

    result = expand_profile_defaults("minimal", [])

    assert len(result) == 1, f"minimal must produce exactly 1 stage, got {[s['id'] for s in result]}"
    review = result[0]
    assert review["id"] == "review"
    assert review["type"] == "review"
    assert review["provider"] == "openai"
    assert review["skill"] == "code-review"
    assert review["gate"] == "blocking"
    assert review["triggers"] == ["pr_opened", "pr_updated"]
    assert review["depends_on"] == []


def test_expand_profile_defaults_standard_shape() -> None:
    """standard profile expands to review + security, both BLOCKING and independent."""
    from stagr.core.normalize import expand_profile_defaults

    result = expand_profile_defaults("standard", [])

    assert len(result) == 2, f"standard must produce exactly 2 stages, got {[s['id'] for s in result]}"
    review = next(s for s in result if s["id"] == "review")
    security = next(s for s in result if s["id"] == "security")

    assert review["type"] == "review"
    assert review["provider"] == "openai"
    assert review["skill"] == "code-review"
    assert review["gate"] == "blocking"
    assert review["triggers"] == ["pr_opened", "pr_updated"]
    assert review["depends_on"] == []

    assert security["type"] == "security"
    assert security["provider"] == "openai"
    assert security["skill"] == "security-review"
    assert security["gate"] == "blocking"
    assert security["triggers"] == ["pr_opened", "pr_updated"]
    assert security["depends_on"] == []


def test_expand_profile_defaults_standard_fills_missing_fields() -> None:
    """standard profile fills all default fields into a stage with only id and type."""
    from stagr.core.normalize import expand_profile_defaults

    minimal_stage = {"id": "review", "type": "review"}
    result = expand_profile_defaults("standard", [minimal_stage])

    review_stage = next(s for s in result if s["id"] == "review")
    assert review_stage.get("provider") == "openai"
    assert review_stage.get("gate") == "blocking"
    assert review_stage.get("skill") == "code-review"
    assert review_stage.get("triggers") == ["pr_opened", "pr_updated"]
    assert review_stage.get("depends_on") == []


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

    stage_with_override = {"id": "review", "type": "review", "gate": "advisory"}
    result = expand_profile_defaults("standard", [stage_with_override])

    review_stage = next(s for s in result if s["id"] == "review")
    assert review_stage["gate"] == "advisory", (
        f"Operator gate must override profile default: got {review_stage['gate']}"
    )
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


def test_expand_profile_defaults_missing_id_raises() -> None:
    """A stage entry without an 'id' key raises ValueError."""
    from stagr.core.normalize import expand_profile_defaults

    raised = False
    try:
        expand_profile_defaults("custom", [{"type": "review"}])
    except ValueError as exc:
        raised = True
        assert "id" in str(exc).lower(), f"Error must mention 'id': {exc}"
    assert raised, "Expected ValueError for a stage missing 'id'"


def test_expand_profile_defaults_duplicate_ids_raise() -> None:
    """Duplicate stage ids in explicit_stages raise ValueError."""
    from stagr.core.normalize import expand_profile_defaults

    raised = False
    try:
        expand_profile_defaults("custom", [
            {"id": "review", "type": "review"},
            {"id": "review", "type": "review"},
        ])
    except ValueError as exc:
        raised = True
        assert "duplicate" in str(exc).lower(), f"Error must mention 'duplicate': {exc}"
    assert raised, "Expected ValueError for duplicate stage ids"


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
    for stage_id in first_ids:
        stage_first = next(s for s in first_pass if s["id"] == stage_id)
        stage_second = next(s for s in second_pass if s["id"] == stage_id)
        assert stage_first == stage_second, (
            f"Not idempotent for stage '{stage_id}': {stage_first} != {stage_second}"
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
    """standard profile stages (review, security) are in the output even when not explicitly declared."""
    from stagr.core.normalize import expand_profile_defaults

    result = expand_profile_defaults("standard", [])
    output_ids = [s["id"] for s in result]

    assert "review" in output_ids, "standard profile 'review' stage must be in output"
    assert "security" in output_ids, "standard profile 'security' stage must be in output"
    assert len(output_ids) == 2, f"standard profile must produce exactly 2 stages, got {output_ids}"


def test_expand_profile_defaults_nested_lists_are_not_shared() -> None:
    """Mutating nested lists in expansion results does not pollute defaults or operator input.

    Covers two aliasing paths:
    1. Profile defaults: dict(stage_def) shallow-copies module-level data.
    2. Operator input: dict(stage) shallow-copies caller-supplied dicts.
    Both must use deep copies so returned nested containers are fully isolated.
    """
    from stagr.core.normalize import expand_profile_defaults

    # --- path 1: profile defaults isolation ---
    first_result = expand_profile_defaults("standard", [])
    first_review = next(s for s in first_result if s["id"] == "review")

    first_review["triggers"].append("manual")
    first_review["depends_on"].append("some-stage")

    second_result = expand_profile_defaults("standard", [])
    second_review = next(s for s in second_result if s["id"] == "review")

    assert second_review["triggers"] == ["pr_opened", "pr_updated"], (
        f"Module-level triggers were mutated via first result: {second_review['triggers']}"
    )
    assert second_review["depends_on"] == [], (
        f"Module-level depends_on was mutated via first result: {second_review['depends_on']}"
    )

    # --- path 2: operator input isolation ---
    operator_stage = {"id": "review", "triggers": ["pr_opened"]}
    operator_input = [operator_stage]
    expansion_result = expand_profile_defaults("standard", operator_input)
    expanded_review = next(s for s in expansion_result if s["id"] == "review")

    expanded_review["triggers"].append("manual")

    assert operator_stage["triggers"] == ["pr_opened"], (
        f"Operator input triggers were mutated via expansion result: {operator_stage['triggers']}"
    )


def test_expand_profile_defaults_operator_depends_on_survives_expansion() -> None:
    """An operator depends_on override produces a single depends_on field with the operator value.

    Vocabulary boundary test: expand_profile_defaults operates in raw M1 config vocabulary
    where the dependency field is 'depends_on' (as in config.schema.json). An operator who
    explicitly declares depends_on: [build] on a standard profile stage must get exactly that
    value in the output — the profile default depends_on: [] must be replaced, with no
    second 'dependencies' key appearing alongside it.
    """
    from stagr.core.normalize import expand_profile_defaults

    operator_review = {"id": "review", "depends_on": ["build"]}
    result = expand_profile_defaults("standard", [operator_review])

    review_stage = next(s for s in result if s["id"] == "review")

    assert review_stage.get("depends_on") == ["build"], (
        f"Operator depends_on override not preserved: got {review_stage.get('depends_on')}"
    )
    assert "dependencies" not in review_stage, (
        f"No canonical 'dependencies' key should appear at this raw-vocab layer: "
        f"found in {list(review_stage.keys())}"
    )
