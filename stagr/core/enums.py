"""Platform-agnostic enumerations for the Stagr neutral core.

All values are lowercase strings matching the config vocabulary. No platform-
specific names (no GitHub event names, no CI YAML keys) appear here.
"""
from __future__ import annotations

from enum import Enum


class StageKind(str, Enum):
    """The category of work a stage performs."""

    REVIEW = "review"
    SECURITY = "security"
    BUILD = "build"
    TEST = "test"
    DEPLOY = "deploy"
    CUSTOM = "custom"
    IMPLEMENT = "implement"


class StageGate(str, Enum):
    """Whether a stage's conclusion blocks merge."""

    BLOCKING = "blocking"
    NON_BLOCKING = "non_blocking"


class StageTrigger(str, Enum):
    """Event that causes a stage to be invoked."""

    PR_OPENED = "pr_opened"
    PR_UPDATED = "pr_updated"
    MANUAL = "manual"
    ISSUE_LABELED = "issue_labeled"


class AuthorRole(str, Enum):
    """PR author association roles recognised by Stagr.

    Maps to GitHub's author_association values. CONTRIBUTOR (first-time or
    external) is NOT trusted by default — it must be explicitly added to
    TrustPolicy.trustedRoles.
    """

    OWNER = "owner"
    MEMBER = "member"
    COLLABORATOR = "collaborator"
    CONTRIBUTOR = "contributor"


class ForkPolicy(str, Enum):
    """How fork-sourced PRs are handled by generated stage execution artifacts."""

    # Fork PRs never drive any stage execution. Secure default.
    DENY = "deny"
    # Fork PRs may drive unprivileged stages (no requiredSecrets, no write tokens).
    ALLOW_UNPRIVILEGED = "allow_unprivileged"


class MergeMode(str, Enum):
    """Whether the governance artifact auto-merges when all conditions are met."""

    AUTO = "auto"
    MANUAL = "manual"


class InvocationKind(str, Enum):
    """How a BackendRenderer asks the platform to execute a stage."""

    # Post a comment on the PR to trigger the backend.
    PR_COMMENT = "pr_comment"
    # Call the provider's API directly from a CI step.
    API_CALL = "api_call"
    # Trigger a CI workflow by name/id.
    WORKFLOW_DISPATCH = "workflow_dispatch"
    # Insert a native CI component (Action, GitLab component, etc.).
    # Platform-dependent; validated at render time.
    CI_COMPONENT = "ci_component"


class StageResultSignalKind(str, Enum):
    """Platform-native signal mechanism a stage execution artifact uses to publish its result.

    On GitHub V1, CHECK_RUN is required for StageResultSignal. COMMIT_STATUS
    must NOT be used on GitHub V1 — it is forgeable by any statuses:write actor.
    COMMIT_STATUS is available only as a fallback on platforms where Check Runs
    do not exist.
    """

    CHECK_RUN = "check_run"
    WORKFLOW_OUTPUT = "workflow_output"
    COMMIT_STATUS = "commit_status"


class StageResultState(str, Enum):
    """Whether a stage has finished processing (independent of its verdict)."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StageResultConclusion(str, Enum):
    """The verdict of a completed stage."""

    # Stage finished and satisfies the gate (no blocking findings).
    PASS = "pass"
    # Stage finished but findings/conditions prevent a merge-gate pass.
    BLOCKED = "blocked"
    # Stage did not finish (infrastructure failure, dependency failed).
    FAILED = "failed"
    # Signal received but conclusion cannot be determined.
    UNKNOWN = "unknown"


class EvidenceKind(str, Enum):
    """Semantic vocabulary for how stage completion is detected at run time.

    Values are named for what they represent semantically, NOT for platform objects.
    The PlatformRenderer maps each semantic kind to the appropriate platform API.
    Actual platform selectors are backend-defined and opaque to the neutral core.
    """

    REVIEW_RESULT = "review_result"    # a formal review object produced by a reviewer agent
    COMMENT_MATCH = "comment_match"    # a PR comment matching a content selector
    CHECK_RESULT = "check_result"      # a CI check run with a pass/fail conclusion
    WORKFLOW_RESULT = "workflow_result"  # a CI workflow run with a pass/fail conclusion


class EvidenceSuccessCondition(str, Enum):
    """What raw backend output counts as the stage having processed a head commit.

    COMPLETED: operation finished processing, regardless of findings (e.g. code review with findings).
    SUCCESS: operation passed with no failures (e.g. test suite green).
    MATCH_FOUND: a specific pattern is present in the evidence.

    Note: gate satisfaction (PASS vs BLOCKED) is determined by GateDispositionSpec,
    not by EvidenceSuccessCondition. COMPLETED does not mean "satisfies the merge gate."
    """

    COMPLETED = "completed"
    SUCCESS = "success"
    MATCH_FOUND = "match_found"


class GateDispositionKind(str, Enum):
    """How to determine PASS vs BLOCKED given that evidence of completion exists."""

    # PASS if the platform reports zero unresolved review threads for this stage's invocation.
    NO_OPEN_THREADS = "no_open_threads"
    # PASS if a specific completion marker is present in the backend's output.
    EXPLICIT_PASS_MARKER = "explicit_pass_marker"
    # PASS whenever the evidence condition is met (no separate gate check, e.g. build/test stages).
    ALWAYS_PASS = "always_pass"
