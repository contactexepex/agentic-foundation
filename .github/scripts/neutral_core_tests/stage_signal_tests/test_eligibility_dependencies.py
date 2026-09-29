"""Dependency requirements (issue #207): upstream stages must be PASS for the current head.

An upstream signal counts only when it is the single Check Run of that stage on the head written by
the Stagr App and its ``output.summary`` payload says the same stage, head and schema version. The
payload is authoritative; the native Check Run fields are never consulted.
"""
from __future__ import annotations

import json

from neutral_core_tests.stage_signal_tests.eligibility_fixtures import (
    FOREIGN_APP_ID,
    UPSTREAM_CHECK_RUN_NAME,
    build_dependency_documents,
    build_dependency_world,
    build_stage_signal_check_run,
    build_upstream_check_run,
    check_runs_named,
    downstream_config_document,
    downstream_signal,
)
from neutral_core_tests.stage_signal_tests.fixtures import HEAD_SHA, OLD_HEAD_SHA
from neutral_core_tests.stage_signal_tests.job_simulation import run_execute_job
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


def _run(fake, **arguments):
    return run_execute_job(fake, downstream_config_document(), **arguments)


def _assert_downstream_did_nothing(fake, outcome) -> None:
    assert outcome.proceed is False and "invoke" not in outcome.exit_codes, outcome.transcripts
    assert fake.comments_posted_by_writes() == []
    assert downstream_signal(fake) is None


def test_dependency_that_passed_lets_the_stage_start() -> None:
    fake = build_dependency_world([build_upstream_check_run("completed", "pass")])
    outcome = _run(fake)
    assert outcome.proceed is True and set(outcome.exit_codes.values()) == {0}, outcome.transcripts
    assert len(fake.comments_posted_by_writes()) == 1
    assert downstream_signal(fake)["state"] == "running"


def test_dependency_that_has_not_published_yet_gets_no_invocation_and_no_signal() -> None:
    fake = build_dependency_world()
    outcome = _run(fake)
    _assert_downstream_did_nothing(fake, outcome)
    assert "dependency 'review' has not published a valid signal" in outcome.transcripts["eligibility"]


def test_dependency_that_has_not_passed_gets_no_invocation_and_no_signal() -> None:
    for state, conclusion in (("pending", "unknown"), ("running", "unknown"),
                              ("completed", "blocked"), ("completed", "unknown")):
        fake = build_dependency_world([build_upstream_check_run(state, conclusion)])
        outcome = _run(fake)
        _assert_downstream_did_nothing(fake, outcome)
        assert "dependency 'review' has not passed" in outcome.transcripts["eligibility"]


def test_failed_dependency_fails_the_stage_without_invoking_the_backend() -> None:
    fake = build_dependency_world([build_upstream_check_run("failed", "failed")])
    outcome = _run(fake)
    assert outcome.proceed is False and "invoke" not in outcome.exit_codes
    assert fake.comments_posted_by_writes() == [], "the backend was never asked"
    assert downstream_signal(fake) == {
        "schemaVersion": 1, "stageId": "security", "headSha": HEAD_SHA,
        "state": "failed", "conclusion": "failed"}
    (check_run,) = check_runs_named(fake, "stagr/stage/security")
    assert (check_run["status"], check_run["conclusion"]) == ("completed", "failure")


def test_a_completed_dependency_with_a_failed_conclusion_also_propagates() -> None:
    fake = build_dependency_world([build_upstream_check_run("completed", "failed")])
    _run(fake)
    assert downstream_signal(fake)["conclusion"] == "failed" and fake.comments_posted_by_writes() == []


def test_failure_propagation_is_a_single_write_and_repeating_it_changes_nothing() -> None:
    fake = build_dependency_world([build_upstream_check_run("failed", "failed")])
    _run(fake)
    write_count = len(fake.write_calls)
    outcome = _run(fake)
    assert len(fake.write_calls) == write_count and outcome.exit_codes["publish"] == 0


def test_the_payload_is_authoritative_not_the_native_check_run_fields() -> None:
    passed_but_native_failure = build_upstream_check_run("completed", "pass", native_conclusion="failure")
    fake = build_dependency_world([passed_but_native_failure])
    assert _run(fake).proceed is True
    blocked_but_native_success = build_upstream_check_run(
        "completed", "blocked", native_conclusion="success")
    fake = build_dependency_world([blocked_but_native_success])
    _assert_downstream_did_nothing(fake, _run(fake))


def test_pass_forged_by_another_app_is_ignored() -> None:
    forged = build_upstream_check_run("completed", "pass", app_id=FOREIGN_APP_ID)
    fake = build_dependency_world([forged])
    _assert_downstream_did_nothing(fake, _run(fake))


def test_forged_failure_from_another_app_cannot_fail_the_stage() -> None:
    forged = build_upstream_check_run("failed", "failed", app_id=FOREIGN_APP_ID)
    fake = build_dependency_world([forged])
    _assert_downstream_did_nothing(fake, _run(fake))


def test_the_real_signal_decides_when_a_forged_one_sits_next_to_it() -> None:
    real = build_upstream_check_run("running", "unknown")
    forged = build_upstream_check_run("completed", "pass", app_id=FOREIGN_APP_ID, check_run_id=301)
    fake = build_dependency_world([forged, real])
    _assert_downstream_did_nothing(fake, _run(fake))


def test_duplicate_upstream_signals_fail_closed_with_an_error_and_no_write() -> None:
    both_pass = [build_upstream_check_run("completed", "pass"),
                 build_upstream_check_run("completed", "pass", check_run_id=301)]
    fake = build_dependency_world(both_pass)
    outcome = _run(fake)
    assert outcome.exit_codes["eligibility"] == 1 and "::error::" in outcome.transcripts["eligibility"]
    assert "invoke" not in outcome.exit_codes and fake.comments_posted_by_writes() == []
    assert outcome.exit_codes["publish"] == 1 and fake.write_calls == []


def test_upstream_signal_bound_to_a_stale_head_is_ignored() -> None:
    stale_payload = build_upstream_check_run(
        "completed", "pass", head_sha=OLD_HEAD_SHA, listed_head_sha=HEAD_SHA)
    fake = build_dependency_world([stale_payload])
    _assert_downstream_did_nothing(fake, _run(fake))


def test_upstream_pass_that_exists_only_for_the_previous_head_does_not_count() -> None:
    fake = build_dependency_world([build_upstream_check_run("completed", "pass", head_sha=OLD_HEAD_SHA)])
    _assert_downstream_did_nothing(fake, _run(fake))


def test_malformed_or_unsupported_payloads_are_treated_as_not_ready() -> None:
    corruptions = (
        {"schemaVersion": 2}, {"schemaVersion": True}, {"schemaVersion": "1"}, {"schemaVersion": None},
        {"stageId": "other"}, {"stageId": None}, {"headSha": None}, {"headSha": HEAD_SHA.upper()},
        {"state": "done"}, {"state": None}, {"conclusion": "PASS"}, {"conclusion": ["pass"]},
    )
    for corruption in corruptions:
        run = build_upstream_check_run("completed", "pass", payload_overrides=corruption)
        fake = build_dependency_world([run])
        _assert_downstream_did_nothing(fake, _run(fake))


def test_summaries_that_are_not_a_json_object_are_treated_as_not_ready() -> None:
    for summary in ("", "not json", "[]", "null", "42", json.dumps("completed pass")):
        run = build_upstream_check_run("completed", "pass")
        run["output"]["summary"] = summary
        fake = build_dependency_world([run])
        _assert_downstream_did_nothing(fake, _run(fake))
    run = build_upstream_check_run("completed", "pass")
    run["output"] = None
    fake = build_dependency_world([run])
    _assert_downstream_did_nothing(fake, _run(fake))


def test_every_dependency_must_pass() -> None:
    documents = downstream_config_document(dependencies=build_dependency_documents("review", "lint"))
    passed = build_upstream_check_run("completed", "pass")
    for lint_state in (("running", "unknown"), ("completed", "blocked")):
        fake = build_dependency_world([passed, build_stage_signal_check_run("lint", *lint_state, check_run_id=310)])
        outcome = run_execute_job(fake, documents)
        assert outcome.proceed is False and downstream_signal(fake) is None
    fake = build_dependency_world([passed])
    assert run_execute_job(fake, documents).proceed is False, "a missing second dependency waits"
    both = [passed, build_stage_signal_check_run("lint", "completed", "pass", check_run_id=310)]
    assert run_execute_job(build_dependency_world(both), documents).proceed is True


def test_one_failed_dependency_fails_the_stage_even_while_another_is_still_running() -> None:
    documents = downstream_config_document(dependencies=build_dependency_documents("review", "lint"))
    fake = build_dependency_world([
        build_upstream_check_run("running", "unknown"),
        build_stage_signal_check_run("lint", "failed", "failed", check_run_id=310)])
    outcome = run_execute_job(fake, documents)
    assert outcome.proceed is False and downstream_signal(fake)["state"] == "failed"
    assert fake.comments_posted_by_writes() == []


def test_a_stage_without_dependencies_never_looks_for_upstream_signals() -> None:
    fake = build_dependency_world()
    listings: list[str] = []
    original_get_items = fake.get_items
    fake.get_items = lambda path, items_key=None: (
        listings.append(path), original_get_items(path, items_key))[1]
    outcome = run_execute_job(fake, downstream_config_document(dependencies=[]))
    assert outcome.proceed is True
    assert not any(UPSTREAM_CHECK_RUN_NAME.replace("/", "%2F") in path for path in listings)


def test_deserializer_accepts_only_a_payload_bound_to_the_stage_and_head() -> None:
    payload = json.loads(runtime.serialize_signal_payload(
        "review", HEAD_SHA, runtime.StageSignal("completed", "blocked")))
    assert runtime.deserialize_signal_payload(payload, "review", HEAD_SHA) == runtime.StageSignal(
        "completed", "blocked")
    assert runtime.deserialize_signal_payload(payload, "security", HEAD_SHA) is None
    assert runtime.deserialize_signal_payload(payload, "review", OLD_HEAD_SHA) is None
    assert runtime.deserialize_signal_payload(None, "review", HEAD_SHA) is None
    assert runtime.deserialize_signal_payload({}, "review", HEAD_SHA) is None
    for corruption in ({"conclusion": "PASS"}, {"conclusion": ["pass"]}, {"conclusion": None},
                       {"state": "done"}, {"state": ["completed"]}, {"state": None}):
        assert runtime.deserialize_signal_payload({**payload, **corruption}, "review", HEAD_SHA) is None


def test_reasons_never_echo_anything_read_from_an_upstream_payload() -> None:
    hostile = "::error::injected\n::add-mask::secret"
    run = build_upstream_check_run("completed", "pass", payload_overrides={"state": hostile})
    fake = build_dependency_world([run])
    outcome = _run(fake)
    assert "injected" not in outcome.transcripts["eligibility"]
    assert "add-mask" not in outcome.transcripts["eligibility"]
