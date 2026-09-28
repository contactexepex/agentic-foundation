"""Dependency graph construction and acyclicity validation for the normalization pipeline.

Implements two static validation checks:

- **V-S05** — every id in a stage's ``depends_on`` list must exist as an active
  stage id (stages with ``enabled: false`` are already removed before this
  function is called, so a reference to a disabled stage id is a V-S05 error).
- **V-S04** — the dependency graph must be acyclic; a cycle is reported by
  naming every stage id in the cycle-containing component.

The function returns the stages in topological order (dependency-first), which
is the correct execution order for Phase 1 rendering: a stage always appears
after all of its dependencies.

Design source: design-docs/02-canonical-stage-model.md,
               design-docs/07-validation.md (V-S04, V-S05).
"""
from __future__ import annotations

from collections import deque
from typing import Any

from .models import StaticValidationError


def build_and_validate_dag(
    active_stages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate the dependency graph and return stages in topological order.

    Operates in the raw M1 config vocabulary: reads ``depends_on`` (a list of
    stage id strings) from each stage dict.  This function is called after
    enabled-flag filtering, so ``active_stages`` contains only stages with
    ``enabled`` absent or truthy.

    Raises:
        StaticValidationError: V-S05 when a dependency id is not in
            ``active_stages``; V-S04 when the graph contains a cycle (all
            stage ids in the cycle-containing component are named).

    Returns:
        A new list of the same stage dicts in topological order
        (dependency-first).  The input list and its dicts are not mutated.
    """
    stage_id_to_stage: dict[str, dict[str, Any]] = {
        stage["id"]: stage for stage in active_stages
    }

    _check_all_dependency_references_exist(active_stages, stage_id_to_stage)

    return _topological_sort_or_raise(active_stages, stage_id_to_stage)


def _check_all_dependency_references_exist(
    active_stages: list[dict[str, Any]],
    stage_id_to_stage: dict[str, dict[str, Any]],
) -> None:
    """Raise StaticValidationError (V-S05) for any unresolvable dependency reference."""
    for stage in active_stages:
        stage_id = stage["id"]
        for dependency_id in stage.get("depends_on", []):
            if dependency_id not in stage_id_to_stage:
                raise StaticValidationError(
                    f"V-S05: stage '{stage_id}' depends on unknown stage '{dependency_id}'"
                )


def _topological_sort_or_raise(
    active_stages: list[dict[str, Any]],
    stage_id_to_stage: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run Kahn's algorithm; raise StaticValidationError (V-S04) if a cycle exists.

    Kahn's algorithm processes nodes by in-degree.  Any node that is never
    reached (in-degree never drops to zero) is part of a cycle-containing
    component.  We report all such ids in the error message so the operator
    can identify every stage involved.
    """
    in_degree: dict[str, int] = {stage["id"]: 0 for stage in active_stages}
    dependents: dict[str, list[str]] = {stage["id"]: [] for stage in active_stages}

    for stage in active_stages:
        stage_id = stage["id"]
        for dependency_id in stage.get("depends_on", []):
            in_degree[stage_id] += 1
            dependents[dependency_id].append(stage_id)

    processing_queue: deque[str] = deque(
        stage_id for stage_id, degree in in_degree.items() if degree == 0
    )
    topologically_sorted_ids: list[str] = []

    while processing_queue:
        current_id = processing_queue.popleft()
        topologically_sorted_ids.append(current_id)
        for dependent_id in dependents[current_id]:
            in_degree[dependent_id] -= 1
            if in_degree[dependent_id] == 0:
                processing_queue.append(dependent_id)

    if len(topologically_sorted_ids) != len(active_stages):
        cycle_stage_ids = sorted(
            stage_id
            for stage_id, degree in in_degree.items()
            if degree > 0
        )
        raise StaticValidationError(
            f"V-S04: dependency cycle detected among stages: {cycle_stage_ids}"
        )

    return [stage_id_to_stage[stage_id] for stage_id in topologically_sorted_ids]
