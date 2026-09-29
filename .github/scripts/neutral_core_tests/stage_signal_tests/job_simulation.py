"""Runs the steps of a rendered ``execute`` job in order, in process, against the fake GitHub.

The step order and the gating mirror the generated workflow: the eligibility step first; the invoke
step only when eligibility wrote ``proceed=true`` and the previous steps succeeded (GitHub's
implicit ``success()``); the publish step always, told whether the job failed (``!cancelled()``).
The steps call the real ``main`` entry point of the runtime with the environment the workflow
would hand it, so the whole eligibility decision goes through the shared implementation.
"""
from __future__ import annotations

import io
import json
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from neutral_core_tests.stage_signal_tests.fake_github import COMMENTER_TOKEN, REPOSITORY, FakeGitHubApi
from neutral_core_tests.stage_signal_tests.fixtures import HEAD_SHA, PULL_NUMBER
from neutral_core_tests.stage_signal_tests.invocation_fixtures import FIXED_NOW
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


@dataclass
class ExecuteJobOutcome:
    """What one run of the execute job did."""

    exit_codes: dict[str, int] = field(default_factory=dict)
    transcripts: dict[str, str] = field(default_factory=dict)
    proceed: bool | None = None
    output_text: str = ""


def run_execute_job(
    fake: FakeGitHubApi,
    config_document: dict[str, Any],
    event_name: str = "pull_request_target",
    pull_number: str | None = str(PULL_NUMBER),
    event_head_sha: str = HEAD_SHA,
    now: datetime = FIXED_NOW,
    sleep: Callable[[float], None] | None = None,
) -> ExecuteJobOutcome:
    outcome = ExecuteJobOutcome()
    with tempfile.TemporaryDirectory() as directory:
        output_path = Path(directory) / "github_output"
        output_path.write_text("")
        base_environment = {
            "STAGR_STAGE_CONFIG": json.dumps(config_document),
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_OUTPUT": str(output_path),
            "STAGR_PULL_NUMBER": pull_number or "",
            "STAGR_EVENT_HEAD_SHA": event_head_sha,
            "STAGR_EVENT_NAME": event_name,
        }

        def run_step(step: str, mode: str, **extra: str) -> None:
            captured = io.StringIO()
            with redirect_stdout(captured):
                outcome.exit_codes[step] = runtime.main(
                    environment={**base_environment, "STAGR_MODE": mode, **extra},
                    github_api=fake, clock=lambda: now, sleep=sleep or (lambda seconds: None),
                )
            outcome.transcripts[step] = captured.getvalue()

        run_step("eligibility", runtime.MODE_ELIGIBILITY)
        outcome.output_text = output_path.read_text()
        outcome.proceed = "proceed=true" in outcome.output_text
        has_invocation = config_document.get("invocation") is not None
        if outcome.exit_codes["eligibility"] == 0 and outcome.proceed and has_invocation:
            run_step("invoke", runtime.MODE_INVOKE, TRUSTED_COMMENTER_TOKEN=COMMENTER_TOKEN)
        job_failed = any(code != 0 for code in outcome.exit_codes.values())
        run_step("publish", runtime.MODE_PUBLISH,
                 STAGR_JOB_STATUS="failure" if job_failed else "success")
    return outcome
