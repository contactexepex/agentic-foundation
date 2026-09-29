"""EvidenceSpec evaluation: completion is proven only by authentic, head-bound evidence."""
from __future__ import annotations

from neutral_core_tests.stage_signal_tests.fixtures import (
    CODEX_BOT,
    HEAD_SHA,
    OLD_HEAD_SHA,
    build_config,
    build_issue_comment,
    build_summary_body,
    review_evidence_rule,
    security_evidence_rule,
)
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


def _evaluate(comments: list, *rules: dict, head_sha: str = HEAD_SHA) -> runtime.EvidenceOutcome:
    config = build_config(evidence=list(rules) or [review_evidence_rule()])
    return runtime.CommentEvidenceEvaluator(config.evidence_rules).evaluate(comments, head_sha)


def test_completed_review_row_for_the_head_is_evidence() -> None:
    outcome = _evaluate([build_issue_comment(build_summary_body())])
    assert outcome.is_present and len(outcome.matched_bodies) == 1


def test_running_review_row_is_not_evidence() -> None:
    assert not _evaluate([build_issue_comment(build_summary_body(code_review_status="Running"))]).is_present


def test_review_row_completed_for_an_older_head_is_not_evidence() -> None:
    body = build_summary_body(code_review_sha=OLD_HEAD_SHA[:7])
    assert not _evaluate([build_issue_comment(body)]).is_present


def test_review_row_commit_shorter_than_seven_characters_is_not_evidence() -> None:
    assert not _evaluate([build_issue_comment(build_summary_body(code_review_sha=HEAD_SHA[:6]))]).is_present


def test_security_row_does_not_satisfy_the_code_review_rule() -> None:
    """Only the 'Code Review' row counts; a completed Security row for the head is not enough."""
    body = build_summary_body(code_review_status="Running", code_review_sha=OLD_HEAD_SHA[:7])
    assert not _evaluate([build_issue_comment(body)]).is_present


def test_security_marker_completed_for_the_head_is_evidence() -> None:
    assert _evaluate([build_issue_comment(build_summary_body())], security_evidence_rule()).is_present


def test_security_marker_with_running_status_is_not_evidence() -> None:
    """Regression (#235): reducing the selector to its first token accepted status=running."""
    body = build_summary_body(security_status="running")
    assert not _evaluate([build_issue_comment(body)], security_evidence_rule()).is_present


def test_security_marker_completed_for_another_head_is_not_evidence() -> None:
    body = build_summary_body(security_sha=OLD_HEAD_SHA)
    assert not _evaluate([build_issue_comment(body)], security_evidence_rule()).is_present


def test_security_marker_head_must_match_exactly_not_by_prefix() -> None:
    body = build_summary_body(security_sha=HEAD_SHA[:12])
    assert not _evaluate([build_issue_comment(body)], security_evidence_rule()).is_present


def test_comment_from_an_untrusted_human_is_not_evidence() -> None:
    """Regression (#235): anyone can copy the public selector text and the head SHA."""
    forged = build_issue_comment(build_summary_body(), login="attacker", user_type="User")
    assert not _evaluate([forged]).is_present
    assert not _evaluate([forged], security_evidence_rule()).is_present


def test_human_account_named_like_the_bot_is_not_evidence() -> None:
    """A user may register the bot's name without the [bot] suffix; that must not match."""
    lookalike = build_issue_comment(
        build_summary_body(), login="chatgpt-codex-connector", user_type="User"
    )
    assert not _evaluate([lookalike]).is_present


def test_other_bot_is_not_evidence() -> None:
    other_bot = build_issue_comment(build_summary_body(), login="other-app[bot]", user_type="Bot")
    assert not _evaluate([other_bot]).is_present


def test_only_the_latest_producer_comment_is_considered() -> None:
    completed = build_issue_comment(build_summary_body(), comment_id=10)
    newer_running = build_issue_comment(build_summary_body(code_review_status="Running"), comment_id=11)
    assert not _evaluate([completed, newer_running]).is_present
    assert _evaluate([newer_running, completed.copy() | {"id": 12}]).is_present


def test_all_evidence_rules_must_hold() -> None:
    body = build_summary_body(security_status="running")
    outcome = _evaluate([build_issue_comment(body)], review_evidence_rule(), security_evidence_rule())
    assert not outcome.is_present


def test_malformed_marker_json_is_ignored_rather_than_crashing() -> None:
    body = "<!-- codex-security-review:v1 {not json} -->\n" + build_summary_body(security_status="running")
    assert not _evaluate([build_issue_comment(body)], security_evidence_rule()).is_present


def test_no_comments_means_no_evidence() -> None:
    assert not _evaluate([]).is_present


def test_rest_identity_match_requires_bot_type_for_bot_identities() -> None:
    assert runtime.is_rest_user_expected_identity({"login": CODEX_BOT, "type": "Bot"}, CODEX_BOT)
    assert not runtime.is_rest_user_expected_identity({"login": CODEX_BOT, "type": "User"}, CODEX_BOT)
    assert runtime.is_rest_user_expected_identity({"login": "Alice", "type": "User"}, "alice")
    assert not runtime.is_rest_user_expected_identity({"login": "alice", "type": "Bot"}, "alice")
