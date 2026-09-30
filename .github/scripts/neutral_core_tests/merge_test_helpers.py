"""Shared helpers for derive_merge_policy test modules."""
from __future__ import annotations


def make_normalized_stage(
    stage_id: str,
    gate: str = "blocking",
    provider: str = "anthropic",
) -> object:
    """Build a minimal NormalizedStage for use in merge-policy tests."""
    from stagr.core.models import NormalizedStage
    from stagr.core.enums import StageGate, StageKind, StageTrigger

    return NormalizedStage(
        id=stage_id,
        kind=StageKind.REVIEW,
        provider=provider,
        backend="codex",
        skill=None,
        gate=StageGate(gate),
        triggers=(StageTrigger.PR_OPENED,),
        dependencies=(),
    )


def make_config(require_resolved: bool | None = None) -> dict:
    """Build a minimal raw config dict for use in merge-policy tests."""
    config: dict = {}
    if require_resolved is not None:
        config["merge"] = {"discussions": {"require_resolved": require_resolved}}
    return config


def make_trust_policy() -> object:
    """Build a minimal TrustPolicy for use in merge-policy tests."""
    from stagr.core.policy import derive_trust_policy
    return derive_trust_policy({"platform": {}})
