#!/usr/bin/env python3
"""Tests for the `stagr` command line.

Runnable with plain `python .github/scripts/test_cli.py` (no pytest). Exit 0 = pass.
`init`, `doctor`, `plan` and `apply` are not offered today: they return rebuilt on the neutral
core (`plan`/`apply` first), so the CLI only offers `help`.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from stagr import cli  # noqa: E402

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"OK  {message}")
    else:
        failures.append(message)
        print(f"FAIL {message}", file=sys.stderr)


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            exit_code = cli.main(argv)
        except SystemExit as exit_request:
            exit_code = int(exit_request.code or 0)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_help_lists_only_help() -> None:
    exit_code, stdout, _ = run_cli(["help"])
    check(exit_code == 0 and "help" in stdout, "help: `stagr help` lists the available commands")
    for retired_command in ("init", "doctor", "plan", "apply"):
        check(f"\n    {retired_command}" not in stdout, f"help: retired command '{retired_command}' is not offered")


def test_help_for_a_topic() -> None:
    exit_code, stdout, _ = run_cli(["help", "help"])
    check(exit_code == 0 and "topic" in stdout, "help: `stagr help help` details the command")


def test_retired_commands_are_rejected() -> None:
    for retired_command in ("init", "doctor", "plan", "apply"):
        exit_code, _, stderr = run_cli([retired_command])
        check(exit_code != 0 and "invalid choice" in stderr, f"retired command '{retired_command}' exits non-zero")


def test_help_for_unknown_topic_fails() -> None:
    exit_code, _, stderr = run_cli(["help", "nonexistent"])
    check(exit_code == 1 and "unknown command" in stderr, "help: an unknown topic exits 1 and says so")


def main() -> int:
    test_help_lists_only_help()
    test_help_for_a_topic()
    test_retired_commands_are_rejected()
    test_help_for_unknown_topic_fails()
    if failures:
        print(f"\n{len(failures)} test failure(s).", file=sys.stderr)
        return 1
    print("\nAll CLI tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
