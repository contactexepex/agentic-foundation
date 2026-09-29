"""The ``eligibility`` mode of the runtime entry point: its output contract and failure behavior."""
from __future__ import annotations

import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from neutral_core_tests.stage_signal_tests.eligibility_fixtures import downstream_config_document
from neutral_core_tests.stage_signal_tests.fake_github import REPOSITORY, FakeGitHubApi
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    build_config_document,
    build_world,
)
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


def _run_eligibility(
    fake: FakeGitHubApi, config_document: dict, output_path: Path | None, **overrides: str
) -> tuple[int, str]:
    environment = {
        "STAGR_STAGE_CONFIG": json.dumps(config_document), "STAGR_MODE": "eligibility",
        "GITHUB_REPOSITORY": REPOSITORY, "STAGR_PULL_NUMBER": "7", "STAGR_EVENT_HEAD_SHA": HEAD_SHA,
        "STAGR_EVENT_NAME": "pull_request_target",
    }
    if output_path is not None:
        environment["GITHUB_OUTPUT"] = str(output_path)
    environment.update(overrides)
    transcript = io.StringIO()
    with redirect_stdout(transcript):
        exit_code = runtime.main(environment=environment, github_api=fake)
    return exit_code, transcript.getvalue()


def test_step_output_is_exactly_one_constant_line() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output_path = Path(directory) / "output"
        output_path.write_text("")
        _run_eligibility(build_world(), build_config_document(), output_path)
        assert output_path.read_text() == "proceed=true\n"
        output_path.write_text("")
        untrusted = build_world()
        untrusted.pull_requests[7]["author_association"] = "NONE"
        _run_eligibility(untrusted, build_config_document(), output_path)
        assert output_path.read_text() == "proceed=false\n"


def test_step_output_never_carries_text_from_the_event_or_the_pull_request() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output_path = Path(directory) / "output"
        output_path.write_text("")
        hostile = build_world()
        hostile.pull_requests[7]["author_association"] = "NONE\nproceed=true"
        _run_eligibility(hostile, build_config_document(), output_path)
        assert output_path.read_text() == "proceed=false\n"


def test_runs_without_a_step_output_file_and_never_writes_to_github() -> None:
    fake = build_world()
    exit_code, transcript = _run_eligibility(fake, build_config_document(), None)
    assert exit_code == 0 and "eligible" in transcript and fake.write_calls == []


def test_an_api_failure_fails_the_step_and_leaves_the_output_unset() -> None:
    fake = build_world()
    fake.failing_path_fragments.add("pulls/7")
    with tempfile.TemporaryDirectory() as directory:
        output_path = Path(directory) / "output"
        output_path.write_text("")
        exit_code, transcript = _run_eligibility(fake, build_config_document(), output_path)
        assert exit_code == 1 and "::error::" in transcript
        assert output_path.read_text() == "", "no proceed value: the invoke step must not run"


def test_a_stage_with_dependencies_fails_the_step_when_the_check_run_listing_fails() -> None:
    fake = build_world()
    fake.failing_path_fragments.add("check-runs")
    exit_code, transcript = _run_eligibility(fake, downstream_config_document(), None)
    assert exit_code == 1 and "::error::" in transcript


def test_an_unknown_mode_is_rejected_and_the_wakeup_event_names_are_recognised() -> None:
    exit_code, transcript = _run_eligibility(build_world(), build_config_document(), None, STAGR_MODE="wakeup")
    assert exit_code == 1 and "Unknown STAGR_MODE" in transcript
    for event_name, expected in (("check_run", True), ("check_suite", True), ("pull_request_target", False),
                                 ("issue_comment", False), ("schedule", False), (None, False)):
        assert runtime.ReconcileRequest("publish", 7, event_name=event_name).is_dependency_wakeup is expected
