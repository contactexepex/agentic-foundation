"""Post-expansion disabled-stage filtering for the normalization pipeline.

This module owns the ``filter_disabled_stages`` step, which runs **after**
profile expansion and operator override merging but **before** backend/model
resolution, dependency graph construction, and ``NormalizedStage`` production.

Pipeline order (design-docs/02-canonical-stage-model.md line 129):
  1. Raw config parsing
  2. Profile expansion + operator override merging
  3. ``enabled: false`` filtering  ← this module
  4. Backend/model resolution
  5. Dependency graph construction and validation
  6. ``NormalizedStage[]`` production

Design source: design-docs/02-canonical-stage-model.md
"""
from __future__ import annotations

from typing import Any


def filter_disabled_stages(merged_stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the enabled stages from a post-expansion merged stage list.

    ``filter_disabled_stages`` runs **after** profile expansion and operator
    override merging, but before backend/model resolution, dependency graph
    construction, and ``NormalizedStage`` production.  A stage with
    ``enabled: false`` is excluded from the active stage set entirely — it does
    not appear in ``NormalizedStage[]``, is not a valid dependency target, and
    does not contribute to ``MergePolicy.blockingStageIds``.

    This placement (Option B) means that an operator-supplied
    ``{id: <profile-stage-id>, enabled: false}`` entry correctly suppresses the
    profile-provided stage of the same id after the two are merged together.

    The function is pure: it does not mutate the input list or any of its
    entries. It returns a new list containing references to the original dicts
    (shallow copies are unnecessary because the dicts themselves are not
    modified).

    Args:
        merged_stages: The merged list of stage dicts produced by
            ``expand_stages`` after profile expansion and operator override
            application.  Each entry must be a dict; callers are responsible
            for validating that invariant before calling here.

    Returns:
        A new list containing only those dicts whose ``enabled`` field is
        absent or truthy.

    Note:
        Dependency validation (V-S02): an active stage must not declare a
        dependency on a disabled stage id.  That check is part of the
        dependency graph construction step (#182) that follows this one.
    """
    return [stage for stage in merged_stages if stage.get("enabled", True)]
