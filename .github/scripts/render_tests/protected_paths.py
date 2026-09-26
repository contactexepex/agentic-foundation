"""Fixture-based tests for the control-plane protected-paths guard.

The auto-merge gate must not merge a PR that touches any file matched by the
default `merge.protected_paths` set (`.github/workflows/**` and `.agentic/**`);
such PRs are left for a human. Requires bash+jq (present on CI and in this dev
image); the tests skip loudly rather than pass silently when they are absent.
"""
from __future__ import annotations

import json
import shutil

from .harness import check
from .gate_behavior import _merges


def test_protected_paths_guard() -> None:
    if not (shutil.which("bash") and shutil.which("jq")):
        check(False, "protected-paths: bash+jq required to run behavioral fixtures")
        return

    # Default protected path: .github/workflows/**
    check(
        not _merges({"FILES_JSON": json.dumps([[{"filename": ".github/workflows/auto-merge.yml"}]])}),
        "protected-paths: a PR changing .github/workflows/** is not auto-merged (left for a human)",
    )

    # Default protected path: .agentic/**
    check(
        not _merges({"FILES_JSON": json.dumps([[{"filename": ".agentic/config.yml"}]])}),
        "protected-paths: a PR changing .agentic/** is not auto-merged (left for a human)",
    )

    # A PR touching only non-protected paths must not be blocked by the guard.
    check(
        _merges({"FILES_JSON": json.dumps([[{"filename": "src/app.py"}]])}),
        "protected-paths: a PR touching only non-protected paths is not blocked by the guard",
    )
