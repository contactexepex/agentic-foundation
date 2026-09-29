"""Static validation checks V-S07, V-S08, and V-S09 for the Stagr neutral core.

These checks run after normalization and before rendering begins.

**V-S07** — BackendRenderer availability: every ``(provider, backend)`` pair
in the normalized stage list has a registered ``BackendRenderer``. Uses
``registry.has(provider, backend)``.

**V-S08** — Platform invocation compatibility: the target platform supports
every ``InvocationKind`` that the backend renderers would produce. Catches
``CI_COMPONENT`` on a platform that does not support it. Prerequisite: V-S07
must pass so all backend renderers are available. Calls each stage's renderer
to obtain the ``ExecutionPlan.invocation.kind`` and checks it against the
caller-supplied ``supported_invocation_kinds`` set.

**V-S09** — Route dependency-closure: when ``fast_path.enabled: true`` the
stage set for each route (``fast`` and ``normal``) must be
dependency-closed. If stage S is in the route set and S declares dependency D,
then D must also be in the set. The error names the stage and the missing
dependency. This check is skipped entirely when
``routing_policy.fast_path`` is ``None``.

**V-S10** — MergePolicy non-empty blocking stages: when the merge policy runs in
``AUTO`` mode, ``blocking_stage_ids`` must be non-empty. A merge gate with no
blocking stages is trivially satisfied and almost certainly a misconfiguration.

**V-S11** — Dormant routing configuration: when ``routing.fast_path.enabled`` is
false but ``globs`` or ``stages`` keys are still present, a *warning* (never an
error) is produced, because the routing keys will not be evaluated.

**V-S15** — Unenforced merge settings: the generated governance workflow does not query
external check runs, so a non-empty ``merge.required_status_checks`` is a hard error (a
requirement the operator wrote must never be silently dropped), and ``modules.sonar: true``
is a *warning* (V1 fail-open gate that the generated workflow does not evaluate).

**V-S16** — Profile shortcut semantics: ``profile: minimal`` / ``standard`` expand to the
neutral definitions (design-docs/02-canonical-stage-model.md), which differ from the legacy
lane's profiles, so using one produces a *warning* naming the difference.

Design source: design-docs/07-validation.md (V-S07 through V-S16).
"""
from __future__ import annotations

from typing import Any

from .backend_renderer_registry import BackendRendererRegistry
from .enums import InvocationKind, MergeMode
from .models import MergePolicy, NormalizedStage, RoutingPolicy, StaticValidationError

DORMANT_ROUTING_WARNING = (
    "V-S11: dormant route configuration - fast_path is disabled; routing keys are present "
    "but will not be evaluated"
)


def validate_backend_renderer_availability(
    normalized_stages: tuple[NormalizedStage, ...],
    registry: BackendRendererRegistry,
) -> None:
    """Raise ``StaticValidationError`` (V-S07) for any unregistered backend.

    Checks every ``(provider, backend)`` pair that appears in
    ``normalized_stages`` against ``registry.has(provider, backend)``.  The
    first missing pair raises immediately, naming the pair and the stage.

    Args:
        normalized_stages: Stages produced by the normalization pipeline.
        registry: The ``BackendRendererRegistry`` populated before validation.

    Raises:
        StaticValidationError: V-S07 when a ``(provider, backend)`` pair has
            no registered renderer.
    """
    for stage in normalized_stages:
        if not registry.has(stage.provider, stage.backend):
            raise StaticValidationError(
                f"V-S07: no BackendRenderer registered for "
                f"provider={stage.provider!r}, backend={stage.backend!r} "
                f"(stage '{stage.id}')"
            )


def validate_platform_invocation_compatibility(
    normalized_stages: tuple[NormalizedStage, ...],
    registry: BackendRendererRegistry,
    supported_invocation_kinds: frozenset[InvocationKind],
) -> None:
    """Raise ``StaticValidationError`` (V-S08) when a stage uses an unsupported kind.

    Calls each stage's registered ``BackendRenderer.render(stage)`` to obtain
    the ``ExecutionPlan``, then checks that
    ``plan.invocation.kind in supported_invocation_kinds``.

    Prerequisite: V-S07 must pass before this function is called; all backend
    renderers in ``registry`` must be available.

    Args:
        normalized_stages: Stages produced by the normalization pipeline.
        registry: The ``BackendRendererRegistry`` populated before validation.
        supported_invocation_kinds: The set of ``InvocationKind`` values the
            target platform renderer supports.  Typically the caller reads this
            from the concrete ``PlatformRenderer`` class.

    Raises:
        StaticValidationError: V-S08 when a stage's backend renderer produces
            an ``InvocationKind`` not in ``supported_invocation_kinds``, or when the
            backend renderer rejects the stage (raises ``ValueError``).
    """
    for stage in normalized_stages:
        backend_renderer = registry.get(stage.provider, stage.backend)
        try:
            execution_plan = backend_renderer.render(stage)
        except ValueError as renderer_rejection:
            raise StaticValidationError(
                f"V-S08: the BackendRenderer for stage '{stage.id}' "
                f"(provider={stage.provider!r}, backend={stage.backend!r}) rejected the stage: "
                f"{renderer_rejection}"
            ) from renderer_rejection
        if execution_plan.invocation.kind not in supported_invocation_kinds:
            raise StaticValidationError(
                f"V-S08: platform does not support invocation kind "
                f"{execution_plan.invocation.kind.value!r} required by "
                f"stage '{stage.id}' "
                f"(provider={stage.provider!r}, backend={stage.backend!r})"
            )


def validate_route_dependency_closure(
    routing_policy: RoutingPolicy,
    normalized_stages: tuple[NormalizedStage, ...],
) -> None:
    """Raise ``StaticValidationError`` (V-S09) for any non-closed route stage set.

    When ``routing_policy.fast_path`` is ``None`` (fast-path disabled), this
    function returns immediately without performing any check.

    When fast-path is enabled, both the ``fast`` and ``normal`` route stage
    sets are checked for dependency-closure: for every stage S in the set, all
    of S's declared ``dependencies`` must also be in the set.  The first
    violation raises immediately, naming the route, the stage, and the missing
    dependency.

    Args:
        routing_policy: The ``RoutingPolicy`` derived from the config.  When
            ``fast_path`` is ``None`` the check is skipped.
        normalized_stages: Stages produced by the normalization pipeline.
            Stages listed in the route sets but absent from this tuple are
            ignored (their reference validity is covered by V-S05).

    Raises:
        StaticValidationError: V-S09 when a route stage set is not
            dependency-closed, naming the route, the stage, and the missing
            dependency.
    """
    if routing_policy.fast_path is None:
        return

    stage_by_id: dict[str, NormalizedStage] = {stage.id: stage for stage in normalized_stages}

    route_stage_sets: dict[str, tuple[str, ...]] = {
        "fast": routing_policy.fast_path.stages.fast,
        "normal": routing_policy.fast_path.stages.normal,
    }

    for route_name, stage_ids in route_stage_sets.items():
        stage_id_set: set[str] = set(stage_ids)
        for stage_id in stage_ids:
            if stage_id not in stage_by_id:
                # Unknown ids are a V-S05 concern; skip here to avoid double-reporting.
                continue
            stage = stage_by_id[stage_id]
            for dependency_id in stage.dependencies:
                if dependency_id not in stage_id_set:
                    raise StaticValidationError(
                        f"V-S09: route '{route_name}' is not dependency-closed: "
                        f"stage '{stage_id}' depends on '{dependency_id}' "
                        f"which is not in the route set"
                    )


def validate_merge_policy_has_blocking_stages(merge_policy: MergePolicy) -> None:
    """Raise ``StaticValidationError`` (V-S10) for an auto-merge gate with no blocking stage.

    Only ``MergeMode.AUTO`` is checked; a manual merge policy may legitimately have
    no blocking stages.

    Raises:
        StaticValidationError: V-S10 when ``merge_policy.mode`` is ``AUTO`` and
            ``merge_policy.blocking_stage_ids`` is empty.
    """
    if merge_policy.mode is MergeMode.AUTO and not merge_policy.blocking_stage_ids:
        raise StaticValidationError(
            "V-S10: modules.auto_merge is true but no enabled stage has gate: blocking; an "
            "auto-merge gate with no blocking stages is trivially satisfied. Mark at least one "
            "stage gate: blocking or set modules.auto_merge to false"
        )


def collect_dormant_routing_warnings(config: dict[str, Any]) -> tuple[str, ...]:
    """Return the V-S11 warning when fast-path is disabled but routing keys remain.

    A disabled ``routing.fast_path`` that still carries ``globs`` or ``stages`` is
    allowed (the operator may be preparing to enable it), so this never raises; it
    returns a one-element tuple with the warning text, or an empty tuple.
    """
    routing_config: dict[str, Any] = config.get("routing") or {}
    fast_path_config: dict[str, Any] = routing_config.get("fast_path") or {}
    if fast_path_config.get("enabled", True):
        return ()
    if "globs" in fast_path_config or "stages" in fast_path_config:
        return (DORMANT_ROUTING_WARNING,)
    return ()


def validate_merge_settings_are_enforceable(config: dict[str, Any]) -> None:
    """Raise ``StaticValidationError`` (V-S15) when required external checks would be dropped.

    The neutral pipeline derives a ``MergePolicy`` that carries stage results, discussions and the
    deprecated ``modules.sonar`` gate; it has no representation of ``merge.required_status_checks``,
    and the generated governance workflow never queries the named check runs or their App ids. Accepting
    the setting would let the gate pass while a check the operator declared mandatory is missing or red.

    Raises:
        StaticValidationError: V-S15 when ``merge.required_status_checks`` is a non-empty list.
    """
    merge_config: dict[str, Any] = config.get("merge") or {}
    if merge_config.get("required_status_checks"):
        raise StaticValidationError(
            "V-S15: merge.required_status_checks is set, but the governance workflow generated by "
            "stagr plan/apply cannot enforce external check runs yet, so the requirement would be "
            "silently dropped. Remove the setting (and enforce the check in branch protection), or keep "
            "using the legacy auto-merge renderer until external-gate enforcement is supported"
        )


def collect_unenforced_sonar_warnings(config: dict[str, Any]) -> tuple[str, ...]:
    """Return the V-S15 warning when ``modules.sonar`` is set but the generated gate cannot evaluate it."""
    modules_config: dict[str, Any] = config.get("modules") or {}
    if modules_config.get("sonar", False):
        return (
            "V-S15: modules.sonar is set, but the governance workflow generated by stagr plan/apply "
            "does not evaluate external check runs; the SonarCloud check is not enforced by it",
        )
    return ()


PROFILE_SHORTCUT_WARNING_TEMPLATE = (
    "V-S16: profile '{profile_name}' expands to the neutral definition, which is a blocking code "
    "review{security_clause} and no implement stage (the legacy '{profile_name}' profile differs); "
    "add an implement stage explicitly if you need one"
)


def collect_profile_shortcut_warnings(config: dict[str, Any]) -> tuple[str, ...]:
    """Return the V-S16 warning when the config uses the ``minimal`` or ``standard`` shortcut."""
    profile_name = config.get("profile")
    if profile_name not in ("minimal", "standard"):
        return ()
    security_clause = " and a blocking security review" if profile_name == "standard" else ""
    return (
        PROFILE_SHORTCUT_WARNING_TEMPLATE.format(profile_name=profile_name, security_clause=security_clause),
    )


def collect_placeholder_invocation_warnings(
    normalized_stages: tuple[NormalizedStage, ...],
    registry: BackendRendererRegistry,
    functional_invocation_kinds: frozenset[InvocationKind],
) -> tuple[str, ...]:
    """Return one warning per stage whose invocation kind is accepted but not yet rendered for real.

    V-S08 passes for every kind the platform *supports*, but some are rendered as a placeholder
    step that does not run the backend. That must never be silent: the generated workflow would
    look installed while doing nothing. Requires V-S07/V-S08 to have passed.
    """
    return tuple(
        f"stage '{stage.id}' uses a {plan.invocation.kind.name} invocation, which this platform "
        f"renders only as a placeholder step: the generated workflow does not run the backend yet"
        for stage in normalized_stages
        for plan in (registry.get(stage.provider, stage.backend).render(stage),)
        if plan.invocation.kind not in functional_invocation_kinds
    )
