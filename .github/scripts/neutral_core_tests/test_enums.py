"""Tests for neutral-core enumerations (issue #173)."""
from __future__ import annotations


def test_enum_string_values() -> None:
    """All enum members have the correct string values per design doc."""
    from stagr.core.enums import (
        AuthorRole,
        EvidenceKind,
        EvidenceSuccessCondition,
        ForkPolicy,
        GateDispositionKind,
        InvocationKind,
        MergeMode,
        StageGate,
        StageKind,
        StageResultConclusion,
        StageResultSignalKind,
        StageResultState,
        StageTrigger,
    )

    # StageKind — neutral-core M2 contract (issue #173)
    assert StageKind("review") is StageKind.REVIEW
    assert StageKind("security") is StageKind.SECURITY
    assert StageKind("build") is StageKind.BUILD
    assert StageKind("test") is StageKind.TEST
    assert StageKind("deploy") is StageKind.DEPLOY
    assert StageKind("custom") is StageKind.CUSTOM
    assert StageKind("implement") is StageKind.IMPLEMENT

    # StageGate — neutral-core M2 contract (issue #173)
    assert StageGate("blocking") is StageGate.BLOCKING
    assert StageGate("non_blocking") is StageGate.NON_BLOCKING

    # StageTrigger — neutral-core M2 contract (issue #173)
    assert StageTrigger("pr_opened") is StageTrigger.PR_OPENED
    assert StageTrigger("pr_updated") is StageTrigger.PR_UPDATED
    assert StageTrigger("manual") is StageTrigger.MANUAL
    assert StageTrigger("issue_labeled") is StageTrigger.ISSUE_LABELED

    # AuthorRole — CONTRIBUTOR must exist but is not trusted by default
    assert AuthorRole("contributor") is AuthorRole.CONTRIBUTOR
    assert AuthorRole("owner") is AuthorRole.OWNER

    # ForkPolicy
    assert ForkPolicy("deny") is ForkPolicy.DENY
    assert ForkPolicy("allow_unprivileged") is ForkPolicy.ALLOW_UNPRIVILEGED

    # MergeMode
    assert MergeMode("auto") is MergeMode.AUTO
    assert MergeMode("manual") is MergeMode.MANUAL

    # InvocationKind — neutral-core M2 contract (issue #173)
    assert InvocationKind("pr_comment") is InvocationKind.PR_COMMENT
    assert InvocationKind("workflow_dispatch") is InvocationKind.WORKFLOW_DISPATCH
    assert InvocationKind("ci_component") is InvocationKind.CI_COMPONENT

    # StageResultSignalKind — all three variants exist
    assert StageResultSignalKind("check_run") is StageResultSignalKind.CHECK_RUN
    assert StageResultSignalKind("commit_status") is StageResultSignalKind.COMMIT_STATUS

    # EvidenceSuccessCondition — enum, not dataclass
    assert EvidenceSuccessCondition("completed") is EvidenceSuccessCondition.COMPLETED
    assert EvidenceSuccessCondition("success") is EvidenceSuccessCondition.SUCCESS
    assert EvidenceSuccessCondition("match_found") is EvidenceSuccessCondition.MATCH_FOUND

    # GateDispositionKind
    assert GateDispositionKind("no_open_threads") is GateDispositionKind.NO_OPEN_THREADS
    assert GateDispositionKind("explicit_pass_marker") is GateDispositionKind.EXPLICIT_PASS_MARKER
    assert GateDispositionKind("always_pass") is GateDispositionKind.ALWAYS_PASS

    # StageResultState
    assert StageResultState("completed") is StageResultState.COMPLETED
    assert StageResultState("failed") is StageResultState.FAILED

    # StageResultConclusion — BLOCKED is distinct from FAILED
    assert StageResultConclusion("pass") is StageResultConclusion.PASS
    assert StageResultConclusion("blocked") is StageResultConclusion.BLOCKED
    assert StageResultConclusion("failed") is StageResultConclusion.FAILED
    assert StageResultConclusion("unknown") is StageResultConclusion.UNKNOWN

    # EvidenceKind — semantic names, not platform-object names
    assert EvidenceKind("review_result") is EvidenceKind.REVIEW_RESULT
    assert EvidenceKind("comment_match") is EvidenceKind.COMMENT_MATCH
    assert EvidenceKind("check_result") is EvidenceKind.CHECK_RESULT
    assert EvidenceKind("workflow_result") is EvidenceKind.WORKFLOW_RESULT

    # No platform-specific names in enum values (workflow_dispatch is the contracted M2 value)
    for enum_cls in [StageKind, StageGate, StageTrigger, AuthorRole, ForkPolicy,
                     MergeMode, InvocationKind, StageResultSignalKind,
                     StageResultState, StageResultConclusion, EvidenceKind,
                     EvidenceSuccessCondition, GateDispositionKind]:
        for member in enum_cls:
            val = member.value
            for forbidden in ["pull_request_target", "permissions", "github_token"]:
                assert forbidden not in val.lower(), \
                    f"{enum_cls.__name__}.{member.name} value '{val}' contains platform-specific name"
