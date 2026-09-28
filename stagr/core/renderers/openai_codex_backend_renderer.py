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

Evidence kinds by stage kind:
- REVIEW stages use ``EvidenceKind.REVIEW_RESULT`` with ``SUCCESS`` to confirm
  the code review ran cleanly (without blocking findings). ``COMPLETED`` would
  fire even when the review has open findings, so ``SUCCESS`` is the correct
  success condition for a clean-pass gate.
- SECURITY stages use ``EvidenceKind.COMMENT_MATCH`` with ``MATCH_FOUND``:
  the security review completion is detected from a comment match rather than
  a formal review object. The selector and SHA field are distinct from the
  code-review summary to allow independent evidence tracking.

Renderer raises ``ValueError`` for any stage kind other than REVIEW or
SECURITY; both review kinds are the only supported backends for this renderer.

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
# SHA (the backtick-formatted SHA in the Code Review row).
_REVIEW_SUMMARY_SHA_FIELD = "review_summary_sha"

# Backend-defined selector for the Codex security-review completion comment,
# distinct from the code-review summary to allow independent evidence tracking.
_CODEX_SECURITY_REVIEW_COMMENT_SELECTOR = "codex-security-review-completion-comment"

# The field within the Codex security-review completion comment that carries
# the head SHA of the reviewed commit.
_SECURITY_REVIEW_COMMENT_SHA_FIELD = "security_review_sha"

# Backend-defined selectors that identify the "Completed" pass-marker for each
# review kind within the Codex summary comment.
_CODE_REVIEW_PASS_MARKER_SELECTOR = "codex_code_review_completed"
_SECURITY_REVIEW_PASS_MARKER_SELECTOR = "codex_security_review_completed"


class OpenAICodexBackendRenderer:
    """BackendRenderer that produces an ExecutionPlan for the OpenAI/Codex backend.

    Handles REVIEW (code review) and SECURITY stages only. The invocation kind
    is PR_COMMENT for both; the comment body and evidence kind differ per stage
    kind. Gate disposition is EXPLICIT_PASS_MARKER (see Spike B finding in
    module docstring). Raises ValueError for any other stage kind.
    """

    provider: str = "openai"
    backend: str = "codex"

    def render(self, stage: NormalizedStage) -> ExecutionPlan:
        """Produce an ExecutionPlan for the given review or security stage.

        The plan declares a PR_COMMENT invocation with the appropriate
        ``@codex`` command, an alias-only required secret, a stage-kind-specific
        EvidenceSpec correlated to the head SHA, and an EXPLICIT_PASS_MARKER gate
        disposition whose selector identifies the relevant completed-row in the
        Codex summary comment.

        Raises ValueError for stage kinds other than REVIEW and SECURITY.
        """
        invocation = Invocation(
            kind=InvocationKind.PR_COMMENT,
            params={"body": self._resolve_codex_comment_command(stage.kind)},
        )

        review_evidence = self._build_evidence_spec(stage.kind)

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

    def _build_evidence_spec(self, stage_kind: StageKind) -> EvidenceSpec:
        """Return the EvidenceSpec appropriate for the stage kind.

        REVIEW stages produce a REVIEW_RESULT spec with SUCCESS (clean pass, not
        merely completed). SECURITY stages produce a COMMENT_MATCH spec with
        MATCH_FOUND using the security-review completion comment selector.
        Raises ValueError for any other stage kind.
        """
        if stage_kind is StageKind.REVIEW:
            return EvidenceSpec(
                kind=EvidenceKind.REVIEW_RESULT,
                selector=_CODEX_REVIEW_SUMMARY_SELECTOR,
                correlation=CorrelationSpec(
                    head_sha=True,
                    sha_field=_REVIEW_SUMMARY_SHA_FIELD,
                ),
                success_condition=EvidenceSuccessCondition.SUCCESS,
            )
        if stage_kind is StageKind.SECURITY:
            return EvidenceSpec(
                kind=EvidenceKind.COMMENT_MATCH,
                selector=_CODEX_SECURITY_REVIEW_COMMENT_SELECTOR,
                correlation=CorrelationSpec(
                    head_sha=True,
                    sha_field=_SECURITY_REVIEW_COMMENT_SHA_FIELD,
                ),
                success_condition=EvidenceSuccessCondition.MATCH_FOUND,
            )
        raise ValueError(
            f"OpenAICodexBackendRenderer does not support stage kind {stage_kind!r}; "
            f"only REVIEW and SECURITY are valid"
        )

    def _resolve_codex_comment_command(self, stage_kind: StageKind) -> str:
        """Return the PR comment body that triggers the correct Codex review kind.

        REVIEW stages use ``@codex review``; SECURITY stages use
        ``@codex security review``. Raises ValueError for any other stage kind.
        """
        if stage_kind is StageKind.REVIEW:
            return _CODEX_CODE_REVIEW_COMMAND
        if stage_kind is StageKind.SECURITY:
            return _CODEX_SECURITY_REVIEW_COMMAND
        raise ValueError(
            f"OpenAICodexBackendRenderer does not support stage kind {stage_kind!r}; "
            f"only REVIEW and SECURITY are valid"
        )

    def _resolve_pass_marker_selector(self, stage_kind: StageKind) -> str:
        """Return the backend-defined pass-marker selector for the stage kind.

        The selector identifies which "Completed" row in the Codex summary
        comment constitutes a gate pass for this stage's invocation.
        Raises ValueError for any other stage kind.
        """
        if stage_kind is StageKind.REVIEW:
            return _CODE_REVIEW_PASS_MARKER_SELECTOR
        if stage_kind is StageKind.SECURITY:
            return _SECURITY_REVIEW_PASS_MARKER_SELECTOR
        raise ValueError(
            f"OpenAICodexBackendRenderer does not support stage kind {stage_kind!r}; "
            f"only REVIEW and SECURITY are valid"
        )
