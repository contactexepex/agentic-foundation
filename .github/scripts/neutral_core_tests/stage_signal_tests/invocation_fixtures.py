"""Builders for the backend invocation tests (issue #205): lease markers, clocks, an invoker."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from neutral_core_tests.stage_signal_tests.fake_github import (
    COMMENTER_ASSOCIATION,
    COMMENTER_USER,
    REPOSITORY,
    FakeGitHubApi,
)
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    STAGE_ID,
    build_config,
    request,
)
from stagr.platforms.github.runtime import stage_signal_runtime as runtime

FIXED_NOW = datetime(2026, 9, 29, 18, 0, 0, tzinfo=timezone.utc)
INVOCATION_BODY = "@codex review"


def build_marker_comment(
    expires_at: datetime,
    comment_id: int = 50,
    stage_id: str = STAGE_ID,
    head_sha: str = HEAD_SHA,
    author: dict[str, Any] | None = None,
    author_association: str = COMMENTER_ASSOCIATION,
) -> dict[str, Any]:
    """An invocation comment as the GitHub REST API returns it (default: by the trusted account)."""
    marker = runtime.format_lease_marker(stage_id, head_sha, expires_at)
    return {
        "id": comment_id,
        "body": f"{INVOCATION_BODY}\n\n{marker}",
        "user": dict(COMMENTER_USER if author is None else author),
        "author_association": author_association,
    }


def unexpired_marker_comment(**overrides: Any) -> dict[str, Any]:
    return build_marker_comment(FIXED_NOW + timedelta(minutes=10), **overrides)


def expired_marker_comment(**overrides: Any) -> dict[str, Any]:
    return build_marker_comment(FIXED_NOW - timedelta(minutes=1), **overrides)


def invoke(
    fake: FakeGitHubApi,
    event_head_sha: str | None = HEAD_SHA,
    now: datetime = FIXED_NOW,
    **config_overrides: Any,
) -> runtime.ReconcileResult:
    invoker = runtime.BackendInvoker(
        build_config(**config_overrides), fake, REPOSITORY, lambda: now
    )
    return invoker.invoke_if_needed(request(runtime.MODE_INVOKE, event_head_sha=event_head_sha))


def posted_bodies(fake: FakeGitHubApi) -> list[str]:
    return [call["body"] for call in fake.comments_posted_by_writes()]
