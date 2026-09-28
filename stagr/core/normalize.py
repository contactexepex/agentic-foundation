"""Pre-normalization pipeline for stage config entries.

This module owns the first step of the normalization pipeline: removing stages
that have been explicitly disabled via ``enabled: false`` before any further
processing (profile expansion, dependency validation, NormalizedStage construction).

Design source: design-docs/02-canonical-stage-model.md
"""
from __future__ import annotations

from typing import Any


def filter_disabled_stages(raw_stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the enabled stages from a raw config stage list.

    A stage is included when its ``enabled`` field is absent (defaults to
    ``True``) or explicitly set to a truthy value. A stage with
    ``enabled: false`` is excluded entirely — it must never appear in the
    normalization pipeline, in ``NormalizedStage[]``, in ``blockingStageIds``,
    or as a valid dependency target.

    The function is pure: it does not mutate the input list or any of its
    entries. It returns a new list containing references to the original dicts
    (shallow copies are unnecessary because the dicts themselves are not
    modified).

    Args:
        raw_stages: The raw list of stage dicts read directly from the M1 config
            (``cfg["stages"]``). Each entry must be a dict; callers are
            responsible for validating that invariant before calling here.

    Returns:
        A new list containing only those dicts whose ``enabled`` field is
        absent or truthy.
    """
    return [stage for stage in raw_stages if stage.get("enabled", True)]
