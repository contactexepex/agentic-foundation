"""Render-time configuration of the stage signal runtime (issue #206).

``build_stage_signal_config`` turns an ``ExecutionPlan`` into the JSON document that the generated
workflow hands to ``runtime/stage_signal_runtime.py``. All per-stage data reaches the runtime as this
one document, never as text spliced into script source, so a backend-defined selector or identity
cannot break out of (or inject into) the generated code.

The builder fails closed: any plan the GitHub runtime cannot evaluate EXACTLY raises ``ValueError``
here, at ``stagr apply`` time, instead of degrading into a weaker check at run time. Unsupported:
- evidence kinds other than the comment-based ``REVIEW_RESULT`` and ``COMMENT_MATCH``;
- evidence that is not head-bound, has an unknown ``sha_field``, or lacks ``produced_by``;
- ``FindingScopeSpec.invocation_correlation`` (GitHub V1 has no reliable binding for it);
- a plan without evidence whose invocation completes asynchronously (``PR_COMMENT`` or
  ``WORKFLOW_DISPATCH``): nothing could ever prove it finished, and reporting PASS after merely
  posting the request would be a false signal;
- a ``PR_COMMENT`` invocation (issue #205) without a non-empty ``params["body"]``, without the
  ``TRUSTED_COMMENTER_TOKEN`` secret it must be posted with, or with a ``params["lease_minutes"]``
  that is not an integer from 1 to ``MAX_LEASE_MINUTES``. The lease defaults to 30 minutes.
Other invocation kinds are not posted by this runtime yet and carry no ``invocation`` document.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from stagr.core.enums import (
    EvidenceKind,
    EvidenceSuccessCondition,
    ForkPolicy,
    GateDispositionKind,
    InvocationKind,
)
from stagr.core.models import EvidenceSpec, ExecutionPlan, NormalizedStage, RenderContext
from stagr.platforms.github.runtime.stage_signal_runtime import (
    DEFAULT_LEASE_MINUTES,
    INVOCATION_KIND_PR_COMMENT,
    MAX_LEASE_MINUTES,
    TRUSTED_COMMENTER_TOKEN_VARIABLE,
)

# Invocations that run to completion inside the execute job, so the job's own outcome is the proof.
_SYNCHRONOUS_INVOCATION_KINDS = frozenset({InvocationKind.CI_COMPONENT, InvocationKind.API_CALL})

# The "Code Review" row of the Codex review-summary table; see the runtime's REVIEW_RESULT handling.
_REVIEW_SUMMARY_SHA_FIELD = "review_summary_sha"

# GitHub login: alphanumerics and single hyphens, optionally suffixed "[bot]". Also the only
# character set allowed into the job-level ``if:`` expression, which embeds the login as a literal.
_GITHUB_LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?$")

_GITHUB_EXPRESSION_OPENER = "${{"


@dataclass(frozen=True)
class StageSignalConfig:
    """The validated runtime configuration plus the facts the workflow assembly needs."""

    document: dict[str, Any]
    evidence_producers: tuple[str, ...]

    @property
    def posts_pull_request_comment_invocation(self) -> bool:
        """True when the execute job posts the backend request itself (``invoke`` mode)."""
        return self.document["invocation"] is not None

    @property
    def has_asynchronous_evidence(self) -> bool:
        """True when completion is observed later (reconcile/sweep) rather than at execute time."""
        return bool(self.document["evidence"])

    def to_json_text(self) -> str:
        return json.dumps(self.document, sort_keys=True, separators=(",", ":"))


def build_stage_signal_config(
    plan: ExecutionPlan,
    stage: NormalizedStage,
    render_context: RenderContext,
    publisher_app_id: str,
    check_run_name: str,
) -> StageSignalConfig:
    """Return the validated runtime configuration for ``stage``; raise ValueError if unsupported."""
    evidence_documents = [_build_evidence_document(stage, spec) for spec in plan.evidence]
    gate_document = _build_gate_document(stage, plan)
    _reject_unprovable_completion(stage, plan)
    trust_policy = render_context.trust_policy
    document = {
        "schemaVersion": 1,
        "stageId": stage.id,
        "checkRunName": check_run_name,
        "publisherAppId": str(publisher_app_id),
        "trustedRoles": sorted(role.value.upper() for role in trust_policy.trusted_roles),
        "denyForks": trust_policy.fork_policy is ForkPolicy.DENY,
        "privilegedStage": bool(plan.required_secrets),
        "evidence": evidence_documents,
        "gate": gate_document,
        "invocation": _build_invocation_document(stage, plan),
    }
    if _GITHUB_EXPRESSION_OPENER in json.dumps(document):
        raise ValueError(
            f"Stage '{stage.id}': the stage signal configuration contains the GitHub expression "
            f"opener, which would be evaluated by Actions when stored in the workflow."
        )
    producers = tuple(dict.fromkeys(item["producedBy"] for item in evidence_documents))
    return StageSignalConfig(document=document, evidence_producers=producers)


def _build_evidence_document(stage: NormalizedStage, spec: EvidenceSpec) -> dict[str, Any]:
    supported_conditions = {
        EvidenceKind.REVIEW_RESULT: EvidenceSuccessCondition.COMPLETED,
        EvidenceKind.COMMENT_MATCH: EvidenceSuccessCondition.MATCH_FOUND,
    }
    if supported_conditions.get(spec.kind) is not spec.success_condition:
        raise ValueError(
            f"Stage '{stage.id}': GitHubPlatformRenderer V1 supports only REVIEW_RESULT with "
            f"COMPLETED and COMMENT_MATCH with MATCH_FOUND; got {spec.kind.name} with "
            f"{spec.success_condition.name}."
        )
    if not spec.correlation.head_sha:
        raise ValueError(
            f"Stage '{stage.id}': evidence must be head-bound (correlation.head_sha=True); an "
            f"unbound item could satisfy the check for a newer commit."
        )
    _require_valid_login(stage, spec.produced_by, "EvidenceSpec.produced_by")
    _require_selector_and_sha_field(stage, spec)
    return {
        "kind": spec.kind.value,
        "selector": spec.selector,
        "shaField": spec.correlation.sha_field,
        "successCondition": spec.success_condition.value,
        "producedBy": spec.produced_by,
    }


def _require_selector_and_sha_field(stage: NormalizedStage, spec: EvidenceSpec) -> None:
    tokens = spec.selector.split()
    if not tokens:
        raise ValueError(f"Stage '{stage.id}': evidence selector must not be empty.")
    if spec.kind is EvidenceKind.REVIEW_RESULT:
        if len(tokens) != 1 or spec.correlation.sha_field != _REVIEW_SUMMARY_SHA_FIELD:
            raise ValueError(
                f"Stage '{stage.id}': REVIEW_RESULT needs a single-token selector and "
                f"sha_field '{_REVIEW_SUMMARY_SHA_FIELD}'; got selector {spec.selector!r} and "
                f"sha_field {spec.correlation.sha_field!r}."
            )
        return
    if not spec.correlation.sha_field.strip() or any("=" not in token for token in tokens[1:]):
        raise ValueError(
            f"Stage '{stage.id}': COMMENT_MATCH needs a sha_field and a selector of the form "
            f"'<marker-prefix> [key=value ...]'; got {spec.selector!r}."
        )


def _build_gate_document(stage: NormalizedStage, plan: ExecutionPlan) -> dict[str, Any]:
    gate = plan.gate_disposition
    created_by, head_sha_bound = "", False
    if gate.kind is GateDispositionKind.NO_OPEN_THREADS:
        scope = gate.scope
        if scope.invocation_correlation is not None:
            raise ValueError(
                f"Stage '{stage.id}': FindingScopeSpec.invocation_correlation is not supported "
                f"by GitHubPlatformRenderer V1 (no reliable binding to review threads); ignoring "
                f"it would silently widen the scope."
            )
        _require_valid_login(stage, scope.created_by, "FindingScopeSpec.created_by")
        created_by, head_sha_bound = scope.created_by, scope.head_sha
    elif gate.kind is GateDispositionKind.EXPLICIT_PASS_MARKER:
        if not gate.selector.strip() or not plan.evidence:
            raise ValueError(
                f"Stage '{stage.id}': EXPLICIT_PASS_MARKER needs a selector and evidence to scan."
            )
    return {
        "kind": gate.kind.value,
        "selector": gate.selector,
        "createdBy": created_by,
        "headShaBound": head_sha_bound,
    }


def _build_invocation_document(stage: NormalizedStage, plan: ExecutionPlan) -> dict[str, Any] | None:
    invocation = plan.invocation
    if invocation.kind is not InvocationKind.PR_COMMENT:
        return None
    body = invocation.params.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError(
            f"Stage '{stage.id}': a PR_COMMENT invocation needs a non-empty params['body'], the "
            f"comment that asks the backend to run; got {body!r}."
        )
    if not any(secret.alias == TRUSTED_COMMENTER_TOKEN_VARIABLE and secret.env_name
               for secret in plan.required_secrets):
        raise ValueError(
            f"Stage '{stage.id}': a PR_COMMENT invocation is posted with the "
            f"{TRUSTED_COMMENTER_TOKEN_VARIABLE} secret, but the plan declares no resolved secret "
            f"with that alias."
        )
    lease_minutes = invocation.params.get("lease_minutes", DEFAULT_LEASE_MINUTES)
    is_integer = isinstance(lease_minutes, int) and not isinstance(lease_minutes, bool)
    if not is_integer or not 1 <= lease_minutes <= MAX_LEASE_MINUTES:
        raise ValueError(
            f"Stage '{stage.id}': invocation params['lease_minutes'] must be an integer from 1 to "
            f"{MAX_LEASE_MINUTES}; got {lease_minutes!r}."
        )
    return {"kind": INVOCATION_KIND_PR_COMMENT, "body": body, "leaseMinutes": lease_minutes}


def _reject_unprovable_completion(stage: NormalizedStage, plan: ExecutionPlan) -> None:
    if plan.evidence or plan.invocation.kind in _SYNCHRONOUS_INVOCATION_KINDS:
        return
    raise ValueError(
        f"Stage '{stage.id}': a {plan.invocation.kind.name} invocation completes asynchronously "
        f"but the plan declares no EvidenceSpec, so nothing could prove it finished. Declare "
        f"evidence, or use a synchronous invocation (CI_COMPONENT or API_CALL)."
    )


def _require_valid_login(stage: NormalizedStage, identity: str | None, field_name: str) -> None:
    if not identity or not _GITHUB_LOGIN_PATTERN.match(identity):
        raise ValueError(
            f"Stage '{stage.id}': {field_name} must be a GitHub login (optionally ending in "
            f"'[bot]') so evidence and findings can be authenticated; got {identity!r}."
        )
