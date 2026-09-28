"""Tests for Invocation, ExecutionPlan, and SecretRef (issue #175)."""
from __future__ import annotations


def test_invocation_params_immutable() -> None:
    """Invocation.params is a read-only mapping — mutation raises TypeError."""
    from stagr.core.models import Invocation
    from stagr.core.enums import InvocationKind

    inv = Invocation(kind=InvocationKind.PR_COMMENT, params={"key": "value"})
    assert inv.params["key"] == "value"
    try:
        inv.params["key"] = "mutated"  # type: ignore[index]
        assert False, "Should have raised TypeError on read-only mapping"
    except TypeError:
        pass


def test_invocation_params_deep_immutable() -> None:
    """Invocation.params is deeply immutable — nested dicts and lists are also frozen."""
    from stagr.core.models import Invocation
    from stagr.core.enums import InvocationKind
    from types import MappingProxyType

    nested = Invocation(
        kind=InvocationKind.WORKFLOW_DISPATCH,
        params={
            "options": {"retries": 3, "flags": ["--verbose", "--fail-fast"]},
            "tags": ["ci", "deploy"],
        },
    )

    # Top-level mapping is frozen
    try:
        nested.params["new_key"] = "bad"  # type: ignore[index]
        assert False, "Should have raised TypeError on top-level write"
    except TypeError:
        pass

    # Nested dict is also a MappingProxyType (frozen)
    assert isinstance(nested.params["options"], MappingProxyType), \
        "Nested dict must become MappingProxyType"
    try:
        nested.params["options"]["retries"] = 99  # type: ignore[index]
        assert False, "Should have raised TypeError on nested dict write"
    except TypeError:
        pass

    # Nested list is converted to tuple
    assert isinstance(nested.params["options"]["flags"], tuple), \
        "Nested list must become tuple"
    assert isinstance(nested.params["tags"], tuple), \
        "Top-level list value must become tuple"

    # Dict inside a tuple is also frozen (tuple elements are recursed)
    tuple_of_dicts = Invocation(
        kind=InvocationKind.WORKFLOW_DISPATCH,
        params={"x": ({"mutable": 1},)},
    )
    assert isinstance(tuple_of_dicts.params["x"], tuple), \
        "Input tuple must remain a tuple"
    assert isinstance(tuple_of_dicts.params["x"][0], MappingProxyType), \
        "Dict inside tuple must become MappingProxyType"
    try:
        tuple_of_dicts.params["x"][0]["mutable"] = 99  # type: ignore[index]
        assert False, "Should have raised TypeError on dict-inside-tuple write"
    except TypeError:
        pass


def test_execution_plan_requires_gate_disposition() -> None:
    """ExecutionPlan without gate_disposition raises ValueError."""
    from stagr.core.models import ExecutionPlan, Invocation
    from stagr.core.enums import InvocationKind

    inv = Invocation(kind=InvocationKind.PR_COMMENT)
    try:
        ExecutionPlan(
            stage_id="review",
            invocation=inv,
            gate_disposition=None,  # type: ignore[arg-type]
        )
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "gate_disposition" in str(exc)


def test_execution_plan_valid() -> None:
    """ExecutionPlan with all required fields constructs and has no platform-specific fields."""
    from stagr.core.models import ExecutionPlan, GateDispositionSpec, Invocation, SecretRef
    from stagr.core.enums import GateDispositionKind, InvocationKind

    inv = Invocation(kind=InvocationKind.PR_COMMENT, params={"comment_template": "review me"})
    gate = GateDispositionSpec(kind=GateDispositionKind.ALWAYS_PASS, selector="build-complete")
    plan = ExecutionPlan(
        stage_id="review",
        invocation=inv,
        gate_disposition=gate,
        required_secrets=(SecretRef(alias="PROVIDER_API_KEY"),),
    )
    assert plan.stage_id == "review"
    assert plan.invocation.kind is InvocationKind.PR_COMMENT
    assert len(plan.required_secrets) == 1
    assert plan.evidence == ()

    # No platform-specific fields
    assert not hasattr(plan, "permissions")
    assert not hasattr(plan, "runs_on")
