"""Tests for validate_dag_acyclicity and validate_dependency_references (V-S04/V-S05).

Covers:
- V-S04: a two-stage cycle raises StaticValidationError naming both stage ids.
- V-S04: a three-stage cycle raises naming all three stage ids.
- V-S04: a valid acyclic dependency graph passes without error.
- V-S05: a depends_on reference to a non-existent stage raises naming the missing id.
- V-S05: a depends_on reference to a stage filtered out (disabled) raises V-S05.
- V-S05: all depends_on references resolved to existing stages passes.
- V-S05: a stage with no depends_on field passes without error.

Exported as DAG_VALIDATOR_TESTS for use by the top-level test runner.
"""
from __future__ import annotations


def test_dag_validator_two_stage_cycle_raises_v_s04() -> None:
    """A two-stage cycle raises V-S04 naming both stage ids."""
    from stagr.core.dag_validator import validate_dag_acyclicity
    from stagr.core.models import StaticValidationError

    stage_build = {"id": "build", "depends_on": ["test"]}
    stage_test = {"id": "test", "depends_on": ["build"]}

    raised = False
    try:
        validate_dag_acyclicity([stage_build, stage_test])
    except StaticValidationError as exc:
        raised = True
        error_message = str(exc)
        assert "V-S04" in error_message, f"Error must reference V-S04: {error_message}"
        assert "'build'" in error_message, f"Error must name stage 'build': {error_message}"
        assert "'test'" in error_message, f"Error must name stage 'test': {error_message}"
    assert raised, "Expected StaticValidationError for a two-stage cycle"


def test_dag_validator_three_stage_cycle_raises_v_s04() -> None:
    """A three-stage cycle (a→b→c→a) raises V-S04 naming all three stage ids."""
    from stagr.core.dag_validator import validate_dag_acyclicity
    from stagr.core.models import StaticValidationError

    stage_a = {"id": "a", "depends_on": ["b"]}
    stage_b = {"id": "b", "depends_on": ["c"]}
    stage_c = {"id": "c", "depends_on": ["a"]}

    raised = False
    try:
        validate_dag_acyclicity([stage_a, stage_b, stage_c])
    except StaticValidationError as exc:
        raised = True
        error_message = str(exc)
        assert "V-S04" in error_message, f"Error must reference V-S04: {error_message}"
        for cycle_member_id in ("a", "b", "c"):
            assert f"'{cycle_member_id}'" in error_message, (
                f"Error must name stage '{cycle_member_id}': {error_message}"
            )
    assert raised, "Expected StaticValidationError for a three-stage cycle"


def test_dag_validator_valid_acyclic_graph_passes() -> None:
    """A valid acyclic dependency graph passes without raising any error."""
    from stagr.core.dag_validator import validate_dag_acyclicity

    stages = [
        {"id": "build"},
        {"id": "test", "depends_on": ["build"]},
        {"id": "deploy", "depends_on": ["test"]},
    ]
    validate_dag_acyclicity(stages)  # must not raise


def test_dag_validator_unknown_dep_raises_v_s05() -> None:
    """A depends_on reference to a non-existent stage id raises V-S05 naming the id."""
    from stagr.core.dag_validator import validate_dependency_references
    from stagr.core.models import StaticValidationError

    stages = [{"id": "test", "depends_on": ["nonexistent"]}]

    raised = False
    try:
        validate_dependency_references(stages)
    except StaticValidationError as exc:
        raised = True
        error_message = str(exc)
        assert "V-S05" in error_message, f"Error must reference V-S05: {error_message}"
        assert "nonexistent" in error_message, (
            f"Error must name the unknown id 'nonexistent': {error_message}"
        )
    assert raised, "Expected StaticValidationError for an unknown dependency reference"


def test_dag_validator_disabled_dep_raises_v_s05() -> None:
    """A depends_on id absent from active stages (filtered out as disabled) raises V-S05.

    Disabled stages are removed upstream by filter_disabled_stages before the
    validators are called; from the validator's perspective the id is simply absent.
    """
    from stagr.core.dag_validator import validate_dependency_references
    from stagr.core.models import StaticValidationError

    # 'was-disabled' was removed from the stage list before this call
    stages = [{"id": "consumer", "depends_on": ["was-disabled"]}]

    raised = False
    try:
        validate_dependency_references(stages)
    except StaticValidationError as exc:
        raised = True
        error_message = str(exc)
        assert "V-S05" in error_message, f"Error must reference V-S05: {error_message}"
        assert "was-disabled" in error_message, (
            f"Error must name the filtered-out id 'was-disabled': {error_message}"
        )
    assert raised, "Expected V-S05 error when depending on a filtered-out (disabled) stage"


def test_dag_validator_valid_dep_references_pass() -> None:
    """All depends_on references resolve to existing stages: no error raised."""
    from stagr.core.dag_validator import validate_dependency_references

    stages = [
        {"id": "build"},
        {"id": "test", "depends_on": ["build"]},
    ]
    validate_dependency_references(stages)  # must not raise


def test_dag_validator_no_depends_on_passes() -> None:
    """A stage with no depends_on field passes both reference and acyclicity checks."""
    from stagr.core.dag_validator import validate_dag_acyclicity, validate_dependency_references

    stages = [{"id": "standalone"}]
    validate_dependency_references(stages)  # must not raise
    validate_dag_acyclicity(stages)          # must not raise


DAG_VALIDATOR_TESTS = [
    test_dag_validator_two_stage_cycle_raises_v_s04,
    test_dag_validator_three_stage_cycle_raises_v_s04,
    test_dag_validator_valid_acyclic_graph_passes,
    test_dag_validator_unknown_dep_raises_v_s05,
    test_dag_validator_disabled_dep_raises_v_s05,
    test_dag_validator_valid_dep_references_pass,
    test_dag_validator_no_depends_on_passes,
]
