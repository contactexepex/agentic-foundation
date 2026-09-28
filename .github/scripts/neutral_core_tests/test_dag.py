"""Tests for build_and_validate_dag (issue #182).

Covers:
- V-S05: unknown dependency reference
- V-S04: cycle detection naming all cycle members
- Linear dependency chains pass and return correct topological order
- Disabled-stage dependency raises V-S05 (the disabled stage is absent from active_stages)
- Stages with no depends_on all pass
- Input dicts are not mutated
- Independent parallel stages both appear in output
"""
from __future__ import annotations


def test_dag_linear_chain_passes() -> None:
    """A linear chain A→B→C passes and C appears before B, B before A."""
    from stagr.core.dag import build_and_validate_dag

    stage_c = {"id": "c"}
    stage_b = {"id": "b", "depends_on": ["c"]}
    stage_a = {"id": "a", "depends_on": ["b"]}

    result = build_and_validate_dag([stage_a, stage_b, stage_c])

    result_ids = [stage["id"] for stage in result]
    assert len(result_ids) == 3, f"Expected 3 stages in result, got {result_ids}"

    position_of_c = result_ids.index("c")
    position_of_b = result_ids.index("b")
    position_of_a = result_ids.index("a")

    assert position_of_c < position_of_b, (
        f"c must appear before b in topological order: {result_ids}"
    )
    assert position_of_b < position_of_a, (
        f"b must appear before a in topological order: {result_ids}"
    )


def test_dag_cycle_raises_v_s04() -> None:
    """A cycle A→B→C→A raises StaticValidationError naming all three stage ids."""
    from stagr.core.dag import build_and_validate_dag
    from stagr.core.models import StaticValidationError

    stage_a = {"id": "a", "depends_on": ["b"]}
    stage_b = {"id": "b", "depends_on": ["c"]}
    stage_c = {"id": "c", "depends_on": ["a"]}

    raised = False
    try:
        build_and_validate_dag([stage_a, stage_b, stage_c])
    except StaticValidationError as exc:
        raised = True
        error_message = str(exc)
        assert "V-S04" in error_message, f"Error must reference V-S04: {error_message}"
        assert "a" in error_message, f"Error must name stage 'a': {error_message}"
        assert "b" in error_message, f"Error must name stage 'b': {error_message}"
        assert "c" in error_message, f"Error must name stage 'c': {error_message}"
    assert raised, "Expected StaticValidationError for a dependency cycle"


def test_dag_unknown_dep_raises_v_s05() -> None:
    """A dependency on a non-existent id raises StaticValidationError naming the bad id."""
    from stagr.core.dag import build_and_validate_dag
    from stagr.core.models import StaticValidationError

    stage_with_bad_dep = {"id": "consumer", "depends_on": ["nonexistent"]}

    raised = False
    try:
        build_and_validate_dag([stage_with_bad_dep])
    except StaticValidationError as exc:
        raised = True
        error_message = str(exc)
        assert "V-S05" in error_message, f"Error must reference V-S05: {error_message}"
        assert "nonexistent" in error_message, (
            f"Error must name the unknown id 'nonexistent': {error_message}"
        )
    assert raised, "Expected StaticValidationError for an unknown dependency reference"


def test_dag_disabled_dep_raises_v_s05() -> None:
    """A stage whose dependency was filtered out (disabled) raises V-S05.

    The disabled stage is not in active_stages — it was removed upstream by
    filter_disabled_stages.  From the DAG's perspective this is identical to
    any other unknown reference: the id simply does not exist in the active set.
    """
    from stagr.core.dag import build_and_validate_dag
    from stagr.core.models import StaticValidationError

    active_stage = {"id": "consumer", "depends_on": ["was-disabled"]}

    raised = False
    try:
        build_and_validate_dag([active_stage])
    except StaticValidationError as exc:
        raised = True
        error_message = str(exc)
        assert "V-S05" in error_message, f"Error must reference V-S05: {error_message}"
        assert "was-disabled" in error_message, (
            f"Error must name the filtered-out id: {error_message}"
        )
    assert raised, "Expected V-S05 error when depending on a disabled (filtered) stage"


def test_dag_no_deps_passes() -> None:
    """Stages with no depends_on all pass and are returned."""
    from stagr.core.dag import build_and_validate_dag

    stages = [
        {"id": "review"},
        {"id": "security"},
        {"id": "build"},
    ]
    result = build_and_validate_dag(stages)

    assert len(result) == 3, f"All 3 independent stages must be returned: got {len(result)}"
    returned_ids = {stage["id"] for stage in result}
    assert returned_ids == {"review", "security", "build"}


def test_dag_does_not_mutate_input() -> None:
    """Input stage dicts are not modified by the function."""
    from stagr.core.dag import build_and_validate_dag

    stage_a = {"id": "a", "depends_on": ["b"]}
    stage_b = {"id": "b"}

    original_a_snapshot = dict(stage_a)
    original_a_deps_snapshot = list(stage_a["depends_on"])
    original_b_snapshot = dict(stage_b)

    build_and_validate_dag([stage_a, stage_b])

    assert stage_a == original_a_snapshot, (
        f"stage_a was mutated: was {original_a_snapshot}, now {stage_a}"
    )
    assert stage_a["depends_on"] == original_a_deps_snapshot, (
        f"stage_a depends_on list was mutated"
    )
    assert stage_b == original_b_snapshot, (
        f"stage_b was mutated: was {original_b_snapshot}, now {stage_b}"
    )


def test_dag_parallel_stages_pass() -> None:
    """Two independent stages (no shared dependencies) both appear in the output."""
    from stagr.core.dag import build_and_validate_dag

    stage_left = {"id": "left", "depends_on": []}
    stage_right = {"id": "right", "depends_on": []}

    result = build_and_validate_dag([stage_left, stage_right])

    returned_ids = {stage["id"] for stage in result}
    assert "left" in returned_ids, "stage 'left' must appear in output"
    assert "right" in returned_ids, "stage 'right' must appear in output"
    assert len(result) == 2, f"Both parallel stages must be returned: got {len(result)}"


def test_dag_empty_active_stages_passes() -> None:
    """An empty active_stages list returns an empty list without error."""
    from stagr.core.dag import build_and_validate_dag

    result = build_and_validate_dag([])
    assert result == [], f"Empty input must produce empty output, got {result}"


def test_dag_direct_two_stage_cycle_raises_v_s04() -> None:
    """A direct two-stage cycle A→B, B→A raises V-S04 naming both ids."""
    from stagr.core.dag import build_and_validate_dag
    from stagr.core.models import StaticValidationError

    stage_a = {"id": "a", "depends_on": ["b"]}
    stage_b = {"id": "b", "depends_on": ["a"]}

    raised = False
    try:
        build_and_validate_dag([stage_a, stage_b])
    except StaticValidationError as exc:
        raised = True
        error_message = str(exc)
        assert "V-S04" in error_message, f"Error must reference V-S04: {error_message}"
        assert "a" in error_message, f"Error must name stage 'a': {error_message}"
        assert "b" in error_message, f"Error must name stage 'b': {error_message}"
    assert raised, "Expected StaticValidationError for a direct two-stage cycle"


def test_dag_cycle_error_excludes_downstream_dependents() -> None:
    """Stages downstream of a cycle are not named in the V-S04 error message.

    When D depends on A, and A and B form a cycle, Kahn's residual set includes
    D (its in-degree never drops to zero because A is never processed).  The
    error must name only actual cycle members A and B, not the innocent
    downstream stage D.
    """
    from stagr.core.dag import build_and_validate_dag
    from stagr.core.models import StaticValidationError

    stage_a = {"id": "a", "depends_on": ["b"]}
    stage_b = {"id": "b", "depends_on": ["a"]}
    stage_d = {"id": "d", "depends_on": ["a"]}

    raised = False
    try:
        build_and_validate_dag([stage_a, stage_b, stage_d])
    except StaticValidationError as exc:
        raised = True
        error_message = str(exc)
        assert "V-S04" in error_message, f"Error must reference V-S04: {error_message}"
        assert "'a'" in error_message, f"Error must name cycle member 'a': {error_message}"
        assert "'b'" in error_message, f"Error must name cycle member 'b': {error_message}"
        assert "'d'" not in error_message, (
            f"Downstream stage 'd' must NOT appear in the cycle error: {error_message}"
        )
    assert raised, "Expected StaticValidationError for a cycle with a downstream dependent"
