"""Static validation V-S04 and V-S05: DAG acyclicity and dependency-reference validity.

- **V-S05** — every id in a stage's ``depends_on`` list must exist in the active
  stage list.  A reference to a stage that was removed by ``filter_disabled_stages``
  is indistinguishable from an unknown reference and is reported as V-S05.
- **V-S04** — the dependency graph must be acyclic.  When a cycle is found, the
  error names every stage id that actually participates in the cycle (downstream
  stages that are merely blocked by a cycle are excluded from the message).

Both validators operate on the expanded, enabled-only stage list produced by
``expand_stages``.  They must be called from the ``validate_config`` front door so
that ``stagr validate`` / ``stagr plan`` / ``stagr apply`` all reject invalid graphs.

Design source: design-docs/07-validation.md (V-S04, V-S05).
"""
from __future__ import annotations

from collections import deque
from typing import Any

from .models import StaticValidationError


def validate_dependency_references(stages: list[dict[str, Any]]) -> None:
    """Raise StaticValidationError (V-S05) for any unresolvable depends_on reference.

    Iterates every stage in ``stages`` and checks that each id listed in
    ``depends_on`` exists in the same list.  Disabled stages must have been
    removed upstream by ``filter_disabled_stages`` before this is called; from
    this validator's perspective a reference to a disabled (absent) stage is
    treated identically to a reference to an unknown stage.

    Args:
        stages: Active (enabled) stage dicts, each containing at least an ``id``
            key and an optional ``depends_on`` list of stage id strings.

    Raises:
        StaticValidationError: V-S05 on the first unresolvable dependency,
            naming the referencing stage id and the missing dependency id.
    """
    known_stage_ids: set[str] = {stage["id"] for stage in stages}
    for stage in stages:
        stage_id = stage["id"]
        for dependency_id in stage.get("depends_on", []) or []:
            if dependency_id not in known_stage_ids:
                raise StaticValidationError(
                    f"V-S05: stage '{stage_id}' depends on unknown stage '{dependency_id}'"
                )


def validate_dag_acyclicity(stages: list[dict[str, Any]]) -> None:
    """Raise StaticValidationError (V-S04) if the dependency graph contains a cycle.

    Runs Kahn's topological-sort algorithm.  If any stages remain unprocessed
    at the end (in-degree never reached zero), a cycle exists.  Only the stage
    ids that are actual cycle participants are named in the error — downstream
    stages whose dependencies are merely blocked by the cycle are excluded.

    Assumes ``validate_dependency_references`` has already passed so that all
    ``depends_on`` entries are resolvable within ``stages``.

    Args:
        stages: Active (enabled) stage dicts, each containing at least an ``id``
            key and an optional ``depends_on`` list of stage id strings.

    Raises:
        StaticValidationError: V-S04 when a cycle is detected, naming all
            cycle-participating stage ids in the error message.
    """
    in_degree: dict[str, int] = {stage["id"]: 0 for stage in stages}
    dependents: dict[str, list[str]] = {stage["id"]: [] for stage in stages}

    for stage in stages:
        for dependency_id in stage.get("depends_on", []) or []:
            if dependency_id in in_degree:
                in_degree[stage["id"]] += 1
                dependents[dependency_id].append(stage["id"])

    processing_queue: deque[str] = deque(
        stage_id for stage_id, degree in in_degree.items() if degree == 0
    )
    processed_count = 0

    while processing_queue:
        current_id = processing_queue.popleft()
        processed_count += 1
        for dependent_id in dependents[current_id]:
            in_degree[dependent_id] -= 1
            if in_degree[dependent_id] == 0:
                processing_queue.append(dependent_id)

    if processed_count != len(stages):
        cycle_member_ids = _find_cycle_member_stage_ids(stages, in_degree)
        sorted_cycle_ids = sorted(cycle_member_ids)
        raise StaticValidationError(
            f"V-S04: dependency cycle detected involving stages: {sorted_cycle_ids}"
        )


def _find_cycle_member_stage_ids(
    stages: list[dict[str, Any]],
    in_degree: dict[str, int],
) -> set[str]:
    """Return the stage ids that are actual cycle participants.

    After Kahn's algorithm, every stage with positive in-degree is in the
    residual subgraph, which includes both cycle members AND acyclic stages
    downstream of a cycle.  This function keeps only the former: a stage is a
    cycle member iff it can reach itself via directed edges in the residual graph.

    Args:
        stages: All active stage dicts (same list passed to the caller).
        in_degree: Kahn's residual in-degree map; positive values indicate nodes
            that were never processed.

    Returns:
        A set of stage ids that are genuine cycle participants.
    """
    residual_ids: frozenset[str] = frozenset(
        stage_id for stage_id, degree in in_degree.items() if degree > 0
    )
    residual_adjacency: dict[str, list[str]] = {
        stage["id"]: [
            dep_id
            for dep_id in stage.get("depends_on", []) or []
            if dep_id in residual_ids
        ]
        for stage in stages
        if stage["id"] in residual_ids
    }

    cycle_members: set[str] = set()
    for start_id in residual_ids:
        if _stage_can_reach_itself(start_id, residual_adjacency):
            cycle_members.add(start_id)
    return cycle_members


def _stage_can_reach_itself(start_id: str, adjacency: dict[str, list[str]]) -> bool:
    """Return True if start_id can reach itself following directed edges in adjacency.

    Args:
        start_id: The stage id to check.
        adjacency: Adjacency list mapping each stage id to its direct dependency ids.

    Returns:
        True if there is a directed path from start_id back to start_id.
    """
    visited: set[str] = set()
    stack: list[str] = list(adjacency.get(start_id, []))
    while stack:
        current_id = stack.pop()
        if current_id == start_id:
            return True
        if current_id not in visited:
            visited.add(current_id)
            stack.extend(adjacency.get(current_id, []))
    return False
