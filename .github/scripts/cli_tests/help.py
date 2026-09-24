"""help-command tests."""
from __future__ import annotations

import io
from contextlib import redirect_stdout

from .harness import check, cli


def test_help_command() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["help"])
    out = buf.getvalue()
    check(rc == 0 and all(c in out for c in ("init", "doctor", "plan", "apply")),
          "help: lists all commands")
    for argv in (["help", "init"], ["init", "help"]):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(argv)
        check(rc == 0 and "--profile" in buf.getvalue(), f"help: `{' '.join(argv)}` details the command")
