"""StageResultSignal <-> Check Run serialization contract (issue #206)."""
from __future__ import annotations

import json

from neutral_core_tests.stage_signal_tests.fixtures import (
    CHECK_RUN_NAME,
    HEAD_SHA,
    STAGE_ID,
    always_pass_gate,
    build_reconciler,
    build_world,
    completed_review_comments,
    build_review_thread,
    request,
)
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


def test_state_maps_to_native_check_run_status_per_issue_table() -> None:
    expected = {"pending": "queued", "running": "in_progress",
                "completed": "completed", "failed": "completed"}
    for state, native_status in expected.items():
        assert runtime.StageSignal(state, "unknown").native_status == native_status, state


def test_conclusion_maps_to_native_check_run_conclusion_per_issue_table() -> None:
    expected = {"pass": "success", "blocked": "action_required",
                "failed": "failure", "unknown": "neutral"}
    for conclusion, native_conclusion in expected.items():
        signal = runtime.StageSignal("completed", conclusion)
        assert signal.native_conclusion == native_conclusion, conclusion


def test_native_conclusion_is_withheld_until_the_run_is_finished() -> None:
    """A conclusion would force status=completed, so pending/running signals must not send one."""
    assert runtime.StageSignal("pending", "unknown").native_conclusion is None
    assert runtime.RUNNING_SIGNAL.native_conclusion is None
    assert runtime.FAILED_SIGNAL.native_status == "completed"
    assert runtime.FAILED_SIGNAL.native_conclusion == "failure"


def test_payload_is_compact_json_with_schema_version_and_lowercase_values() -> None:
    payload_text = runtime.serialize_signal_payload(
        STAGE_ID, HEAD_SHA, runtime.StageSignal("completed", "blocked")
    )
    assert payload_text == (
        '{"schemaVersion":1,"stageId":"review","headSha":"%s",'
        '"state":"completed","conclusion":"blocked"}' % HEAD_SHA
    )
    assert json.loads(payload_text)["schemaVersion"] == 1


def test_pass_is_published_as_success_with_pass_payload() -> None:
    fake = build_world(comments=completed_review_comments())
    reconciler = build_reconciler(fake, gate=always_pass_gate())
    reconciler.reconcile_pull_request(request(runtime.MODE_PUBLISH))
    (check_run,) = fake.check_runs
    assert (check_run["name"], check_run["status"], check_run["conclusion"]) == (
        CHECK_RUN_NAME, "completed", "success")
    assert json.loads(check_run["output"]["summary"])["conclusion"] == "pass"
    assert check_run["output"]["title"]


def test_blocked_is_published_as_action_required_with_blocked_payload() -> None:
    fake = build_world(comments=completed_review_comments(), threads=[build_review_thread()])
    build_reconciler(fake).reconcile_pull_request(request(runtime.MODE_PUBLISH))
    (check_run,) = fake.check_runs
    assert (check_run["status"], check_run["conclusion"]) == ("completed", "action_required")
    payload = json.loads(check_run["output"]["summary"])
    assert (payload["state"], payload["conclusion"]) == ("completed", "blocked")


def test_running_is_published_in_progress_without_a_conclusion() -> None:
    fake = build_world()
    build_reconciler(fake).reconcile_pull_request(request(runtime.MODE_PUBLISH))
    (check_run,) = fake.check_runs
    assert check_run["status"] == "in_progress" and "conclusion" not in check_run
    payload = json.loads(check_run["output"]["summary"])
    assert (payload["state"], payload["conclusion"]) == ("running", "unknown")
    assert payload["headSha"] == HEAD_SHA and payload["stageId"] == STAGE_ID
