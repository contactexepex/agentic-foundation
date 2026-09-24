"""Config-path confinement tests (out-of-repo paths, symlink loops)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .harness import _project_dir, check, cli, render


def test_config_path_confined_to_project_root() -> None:
    # A config/init path resolving outside the project root (CWD) is rejected before any read/write,
    # so an agentic caller cannot be steered into reading or clobbering an arbitrary host file.
    with tempfile.TemporaryDirectory() as outside:
        target = Path(outside) / "secret.yml"
        target.write_text("version: 2\n")
        # doctor refuses to READ an out-of-repo config...
        with _project_dir():
            rc = cli.main(["doctor", "--config", str(target)])
            check(rc == 1, "doctor: refuses a --config outside the project root")
            # ...and init refuses to WRITE outside the repo (even with --force).
            rc_init = cli.main(["init", "--profile", "minimal", "--config", str(target), "--force"])
            check(rc_init == 1 and target.read_text() == "version: 2\n",
                  "init: refuses to write a config outside the project root")
        try:
            render.confine_config_path(target)
            confined = False
        except render.RenderError:
            confined = True
        check(confined, "confine_config_path: rejects a path outside the project root")


def test_config_path_symlink_loop_is_clean_error() -> None:
    # A symlink loop in the path chain makes Path.resolve() raise RuntimeError; confinement must
    # turn that into a clean exit-1 error, not an uncaught traceback.
    with _project_dir() as d:
        a = d / "a"
        b = d / "b"
        os.symlink(b, a)
        os.symlink(a, b)  # a -> b -> a
        rc = cli.main(["init", "--profile", "minimal", "--config", str(a / "config.yml"), "--force"])
        check(rc == 1, "init: a symlink-loop --config exits 1 (clean error, no traceback)")
