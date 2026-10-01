"""Eligibility of the pull request itself (issue #207): trust, forks, current head, open and ready.

Every test runs the whole execute job (eligibility, invoke, publish) through the runtime's entry
point, so "no invocation and no signal" is observed on the fake GitHub, not inferred.
"""
from __future__ import annotations

from neutral_core_tests.stage_signal_tests.eligibility_fixtures import (
    downstream_config_document,
)
from neutral_core_tests.stage_signal_tests.fake_github import FakeGitHubApi
from neutral_core_tests.stage_signal_tests.fixtures import (
    OLD_HEAD_SHA,
    build_config_document,
    build_pull_request,
    build_world,
)
from neutral_core_tests.stage_signal_tests.job_simulation import ExecuteJobOutcome, run_execute_job


def _stage_document(**overrides) -> dict:
    """A dependency-free asynchronous stage, so only the pull request checks are in play."""
    return build_config_document(**overrides)


def _world_with(**pull_request_arguments) -> FakeGitHubApi:
    return build_world(pull_request=build_pull_request(**pull_request_arguments))


def _assert_nothing_happened(fake: FakeGitHubApi, outcome: ExecuteJobOutcome) -> None:
    assert outcome.proceed is False, outcome.transcripts
    assert set(outcome.exit_codes.values()) == {0}, outcome.transcripts
    assert "invoke" not in outcome.exit_codes, "the backend step must not even start"
    assert fake.write_calls == [] and fake.check_runs == [], "no comment and no signal"


def _assert_started(fake: FakeGitHubApi, outcome: ExecuteJobOutcome) -> None:
    assert outcome.proceed is True and set(outcome.exit_codes.values()) == {0}, outcome.transcripts
    assert len(fake.comments_posted_by_writes()) == 1
    (check_run,) = fake.check_runs
    assert '"state":"running"' in check_run["output"]["summary"]


def test_trusted_author_on_the_current_head_starts_the_stage() -> None:
    fake = build_world()
    _assert_started(fake, run_execute_job(fake, _stage_document()))


def test_untrusted_author_role_gets_no_invocation_and_no_signal() -> None:
    for association in ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "MEMBER", ""):
        fake = _world_with(author_association=association)
        _assert_nothing_happened(fake, run_execute_job(fake, _stage_document()))


def test_a_trusted_role_is_matched_case_insensitively_against_the_configured_roles() -> None:
    fake = _world_with(author_association="member")
    document = _stage_document(trustedRoles=["OWNER", "MEMBER"])
    _assert_started(fake, run_execute_job(fake, document))


def test_fork_pull_request_with_the_deny_policy_gets_nothing() -> None:
    fake = _world_with(is_fork=True)
    _assert_nothing_happened(fake, run_execute_job(fake, _stage_document(denyForks=True)))


def test_fork_pull_request_with_allow_unprivileged_proceeds_for_a_non_privileged_stage() -> None:
    fake = _world_with(is_fork=True)
    _assert_started(fake, run_execute_job(fake, _stage_document(denyForks=False, privilegedStage=False)))


def test_fork_pull_request_with_allow_unprivileged_is_still_refused_for_a_privileged_stage() -> None:
    fake = _world_with(is_fork=True)
    document = _stage_document(denyForks=False, privilegedStage=True)
    _assert_nothing_happened(fake, run_execute_job(fake, document))


def test_stale_event_head_gets_no_invocation_and_no_signal() -> None:
    fake = build_world()
    outcome = run_execute_job(fake, _stage_document(), event_head_sha=OLD_HEAD_SHA)
    _assert_nothing_happened(fake, outcome)
    assert "stale" in outcome.transcripts["eligibility"]


def test_closed_and_draft_pull_requests_get_nothing() -> None:
    for arguments in ({"state": "closed"}, {"is_draft": True}):
        fake = _world_with(**arguments)
        _assert_nothing_happened(fake, run_execute_job(fake, _stage_document()))


def test_event_without_a_pull_request_writes_proceed_false_and_touches_nothing() -> None:
    fake = build_world()
    outcome = run_execute_job(fake, _stage_document(), event_name="workflow_dispatch", pull_number="")
    _assert_nothing_happened(fake, outcome)
    assert outcome.output_text == "proceed=false\n", "an explicit false, not an unset output"
    assert "no pull request context" in outcome.transcripts["eligibility"]


def test_eligibility_step_reports_the_reason_and_holds_no_backend_write() -> None:
    fake = _world_with(author_association="NONE")
    outcome = run_execute_job(fake, _stage_document())
    assert "skipped pull request author is not a trusted role" in outcome.transcripts["eligibility"]
    assert not any(method != "GET" for method, _, _ in fake.write_calls)


def test_the_same_pull_request_checks_apply_to_a_stage_with_dependencies() -> None:
    """The dependency stage inherits the pull request checks: an untrusted author never starts it."""
    fake = _world_with(author_association="NONE")
    outcome = run_execute_job(fake, downstream_config_document())
    _assert_nothing_happened(fake, outcome)
