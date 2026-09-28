"""BackendRenderer for the OpenAI/Codex review and security-review backends.

Produces the ExecutionPlan for stages that use Codex (OpenAI's AI code-review
tool) as a PR-comment-driven review backend. Both review (code review) and
security stages share this renderer; the stage kind determines the comment body
posted as the invocation param.

Spike A finding (invocation independence): ``@codex review`` and
``@codex security review`` are independently triggerable PR comments. The
sequential scheduling enforced by the current hand-written workflows is an
operational guard against a Codex backend concurrency limitation (two reviews
running at the same time on one PR), not a protocol requirement of the backend
itself. Each invocation kind is independently valid.

Spike B finding (finding correlation): The GitHub API does not expose a
reliably observable field that unambiguously associates individual review
threads with their originating stage invocation when code review and security
review are performed by the same Codex bot identity on the same head commit.
``pull_request_review_id`` would require a runtime lookup of the formal review
object per thread, and the existing workflows do not record or expose the
per-review discriminator needed to scope thread counts to one stage.
Therefore ``GateDispositionKind.EXPLICIT_PASS_MARKER`` is used in place of
``NO_OPEN_THREADS``. The Codex review-summary comment row that transitions to
"Completed" for the relevant review type serves as the explicit pass marker.

Secret alias contract: only ``SecretRef.alias`` is set here; ``env_name`` is
resolved by the Phase 1 alias-resolution step (see issue #193) before the
PlatformRenderer is invoked.
"""
from __future__ import annotations

from stagr.core.enums import (
    EvidenceKind,
    EvidenceSuccessCondition,
    GateDispositionKind,
    InvocationKind,
    StageKind,
)
from stagr.core.models import (
    CorrelationSpec,
    EvidenceSpec,
    ExecutionPlan,
    GateDispositionSpec,
    Invocation,
    NormalizedStage,
    SecretRef,
)

# Comment bodies posted on the PR to trigger each review kind.
_CODEX_CODE_REVIEW_COMMAND = "@codex review"
_CODEX_SECURITY_REVIEW_COMMAND = "@codex security review"

# Alias for the credential that allows posting PR comments as a trusted user
# (Codex honours @codex commands only from trusted authors, not from the
# github-actions bot). env_name is intentionally absent — alias-only per contract.
_TRUSTED_COMMENTER_TOKEN_ALIAS = "TRUSTED_COMMENTER_TOKEN"

# Backend-defined selector that identifies the Codex review-summary comment
# block; consumed by the PlatformRenderer when constructing the governance
# artifact's evidence-detection logic.
_CODEX_REVIEW_SUMMARY_SELECTOR = "codex-pull-request-review-summary"

# The field within the Codex review-summary evidence item that carries the head
# SHA (the backtick-formatted SHA in the Code Review / Security Review row).
_REVIEW_SUMMARY_SHA_FIELD = "review_summary_sha"

# Backend-defined selectors that identify the "Completed" pass-marker for each
# review kind within the Codex summary comment.
_CODE_REVIEW_PASS_MARKER_SELECTOR = "codex_code_review_completed"
_SECURITY_REVIEW_PASS_MARKER_SELECTOR = "codex_security_review_completed"


class OpenAICodexBackendRenderer:
    """BackendRenderer that produces an ExecutionPlan for the OpenAI/Codex backend.

    Handles both review (code review) and security-review stages. The invocation
    kind is PR_COMMENT for both; the comment body differs per stage kind. Gate
    disposition is EXPLICIT_PASS_MARKER (see Spike B finding in module docstring).
    """

    provider: str = "openai"
    backend: str = "codex"

    def render(self, stage: NormalizedStage) -> ExecutionPlan:
        """Produce an ExecutionPlan for the given review or security stage.

        The plan declares a PR_COMMENT invocation with the appropriate
        ``@codex`` command, an alias-only required secret, a REVIEW_RESULT
        EvidenceSpec correlated to the head SHA, and an EXPLICIT_PASS_MARKER
        gate disposition whose selector identifies the relevant completed-row
        in the Codex summary comment.
        """
        invocation = Invocation(
            kind=InvocationKind.PR_COMMENT,
            params={"body": self._resolve_codex_comment_command(stage.kind)},
        )

        head_sha_correlation = CorrelationSpec(
            head_sha=True,
            sha_field=_REVIEW_SUMMARY_SHA_FIELD,
        )

        review_evidence = EvidenceSpec(
            kind=EvidenceKind.REVIEW_RESULT,
            selector=_CODEX_REVIEW_SUMMARY_SELECTOR,
            correlation=head_sha_correlation,
            success_condition=EvidenceSuccessCondition.COMPLETED,
        )

        gate_disposition = GateDispositionSpec(
            kind=GateDispositionKind.EXPLICIT_PASS_MARKER,
            selector=self._resolve_pass_marker_selector(stage.kind),
        )

        required_secrets = (SecretRef(alias=_TRUSTED_COMMENTER_TOKEN_ALIAS),)

        return ExecutionPlan(
            stage_id=stage.id,
            invocation=invocation,
            gate_disposition=gate_disposition,
            required_secrets=required_secrets,
            evidence=(review_evidence,),
        )

    def _resolve_codex_comment_command(self, stage_kind: StageKind) -> str:
        """Return the PR comment body that triggers the correct Codex review kind.

        Security stages use ``@codex security review``; all other stages (review)
        use ``@codex review``.
        """
        if stage_kind is StageKind.SECURITY:
            return _CODEX_SECURITY_REVIEW_COMMAND
        return _CODEX_CODE_REVIEW_COMMAND

    def _resolve_pass_marker_selector(self, stage_kind: StageKind) -> str:
        """Return the backend-defined pass-marker selector for the stage kind.

        The selector identifies which "Completed" row in the Codex summary
        comment constitutes a gate pass for this stage's invocation.
        """
        if stage_kind is StageKind.SECURITY:
            return _SECURITY_REVIEW_PASS_MARKER_SELECTOR
        return _CODE_REVIEW_PASS_MARKER_SELECTOR
