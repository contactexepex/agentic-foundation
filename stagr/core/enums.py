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

    Actual platform selectors are backend-defined and opaque to the neutral core.
    """

    CHECK_RUN = "check_run"
    PR_COMMENT = "pr_comment"
    WORKFLOW_RUN = "workflow_run"
    COMMIT_STATUS = "commit_status"
