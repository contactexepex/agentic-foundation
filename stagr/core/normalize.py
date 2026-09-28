"""Pre-normalization pipeline for stage config entries.

This module implements the profile expansion step of the normalization pipeline:
merging profile-defined stage defaults with the operator's explicit stage list.

Design source: design-docs/02-canonical-stage-model.md
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Profile stage defaults — declarative data, not code logic.
#
# Each profile maps to a list of stage dicts that supply default field values.
# The operator's own stage fields always override profile defaults (operator wins).
# ``custom`` is the identity profile — no default stages, no field defaults.
#
# Field values use the M1 config vocabulary (lower-case string literals).
# V1 built-in profiles: minimal, standard, full, custom.
# ---------------------------------------------------------------------------
_PROFILE_STAGE_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "minimal": [
        {"id": "implement", "type": "implement", "provider": "anthropic", "gate": "advisory"},
        {"id": "review", "type": "review", "provider": "openai", "gate": "advisory"},
    ],
    "standard": [
        {"id": "implement", "type": "implement", "provider": "anthropic"},
        {"id": "review", "type": "review", "provider": "openai", "gate": "blocking"},
        {"id": "security", "type": "security", "provider": "openai", "gate": "advisory"},
    ],
    "full": [
        {"id": "implement", "type": "implement", "provider": "anthropic"},
        {"id": "security", "type": "security", "provider": "openai", "gate": "blocking"},
        {"id": "test", "type": "test", "provider": "openai", "gate": "blocking"},
        {
            "id": "integration-test",
            "type": "integration-test",
            "provider": "openai",
            "gate": "blocking",
        },
        {"id": "review", "type": "review", "provider": "openai", "gate": "blocking"},
    ],
    "custom": [],
}


def expand_profile_defaults(
    profile_name: str,
    explicit_stages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge profile stage defaults with the operator's explicitly declared stages.

    Implements the profile expansion step of the normalization pipeline
    (design-docs/02-canonical-stage-model.md, "Profile expansion").  The
    returned list is the input to backend/model default resolution and
    subsequent normalization steps.

    Expansion rules:

    - ``custom`` is the identity profile.  ``explicit_stages`` are returned
      as new dicts with no injection — operators must declare every required
      field themselves.
    - For all other built-in profiles, the profile supplies a predefined set
      of stage defaults.  Each profile stage is included in the output.  When
      the operator declares a stage with the same ``id`` as a profile stage,
      the operator's fields are merged *on top of* the profile defaults (the
      operator always wins).  Operator stages whose ``id`` is absent from the
      profile are appended in declaration order.
    - An unrecognised profile name raises ``ValueError`` with error code
      ``V-S01`` (static validation error, caught before any stage processing).

    This function is pure: ``explicit_stages`` and its entries are never
    mutated.  Applying the function twice with the same arguments produces the
    same result (idempotent).

    Args:
        profile_name: The value of the ``profile`` key from the M1 config.
            Operators who omit ``profile`` should pass ``"custom"`` (the
            default in the neutral-core normalization pipeline).
        explicit_stages: The stage list from the M1 config after disabled
            stages have been removed.  Each entry must be a dict containing
            at minimum an ``"id"`` key.

    Returns:
        A new list of new dicts with profile defaults applied.  The caller
        must not rely on identity equality with entries from ``explicit_stages``.

    Raises:
        ValueError: When ``profile_name`` is not a recognised built-in profile
            (V-S01 static validation error).
    """
    if profile_name not in _PROFILE_STAGE_DEFAULTS:
        valid_profile_names = sorted(_PROFILE_STAGE_DEFAULTS)
        raise ValueError(
            f"V-S01: unrecognised profile '{profile_name}' — "
            f"valid profiles are: {valid_profile_names}"
        )

    if profile_name == "custom":
        # Identity profile: no defaults, no extra stages.  Return shallow
        # copies so the caller owns the returned dicts.
        return [dict(stage) for stage in explicit_stages]

    profile_stage_list = _PROFILE_STAGE_DEFAULTS[profile_name]

    # Seed the ordered stage map with profile defaults.
    stage_map: dict[str, dict[str, Any]] = {
        stage_def["id"]: dict(stage_def) for stage_def in profile_stage_list
    }
    output_ordering: list[str] = [stage_def["id"] for stage_def in profile_stage_list]

    # Overlay operator stages: their fields take precedence over profile defaults.
    for stage in explicit_stages:
        stage_id = stage["id"]
        if stage_id in stage_map:
            # Merge operator fields on top of the profile's defaults.
            stage_map[stage_id] = {**stage_map[stage_id], **stage}
        else:
            # Stage not defined by the profile: append in declaration order.
            stage_map[stage_id] = dict(stage)
            output_ordering.append(stage_id)

    return [stage_map[stage_id] for stage_id in output_ordering]
