"""Run the stage signal runtime as a real process against the strict ``gh`` shim."""
from __future__ import annotations

import subprocess
import sys
from typing import Any

from neutral_core_tests.stage_signal_tests.fake_github import (
    REPOSITORY,
    FakeGitHubApi,
    StrictGhCliShim,
)


def run_script_against_fake(
    fake: FakeGitHubApi, script_text: str, **environment_overrides: str
) -> tuple[Any, FakeGitHubApi]:
    """Run ``script_text`` exactly as the workflow does (``python3 -c``), shim ``gh`` on PATH.

    Returns the completed process and the fake's state after the run.
    """
    shim = StrictGhCliShim(fake)
    try:
        environment = shim.environment_with_shim_on_path()
        environment.update(
            GITHUB_REPOSITORY=REPOSITORY,
            GITHUB_SERVER_URL="https://github.com",
            GITHUB_RUN_ID="4242",
        )
        environment.update(environment_overrides)
        completed = subprocess.run(
            [sys.executable, "-c", script_text],
            env=environment, capture_output=True, text=True, check=False,
        )
        return completed, shim.current_state()
    finally:
        shim.cleanup()
