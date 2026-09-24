"""init write/overwrite/symlink guards and value-rejection tests."""
from __future__ import annotations

import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from .harness import _project_dir, check, cli


def test_init_write_and_overwrite_guard() -> None:
    with _project_dir() as d:
        dest = Path(d) / ".agentic" / "config.yml"
        rc = cli.main(["init", "--profile", "minimal", "--config", str(dest)])
        check(rc == 0 and dest.exists(), "init: writes the config file")
        rc2 = cli.main(["init", "--profile", "minimal", "--config", str(dest)])
        check(rc2 == 1, "init: refuses to overwrite an existing file without --force")
        rc3 = cli.main(["init", "--profile", "minimal", "--config", str(dest), "--force"])
        check(rc3 == 0, "init: --force overwrites")


def test_init_refuses_symlink_destination() -> None:
    with _project_dir() as d:
        target = Path(d) / "outside.yml"
        link = Path(d) / "config.yml"
        os.symlink(target, link)  # broken symlink (target does not exist)
        rc = cli.main(["init", "--profile", "minimal", "--config", str(link), "--force"])
        check(rc == 1 and not target.exists(),
              "init: refuses to write through a symlink destination (even with --force)")

    # A symlinked ANCESTOR (e.g. `.agentic` -> outside the checkout) must also be refused: the
    # leaf itself is not a symlink, but writing would follow the parent and escape.
    with _project_dir() as d:
        outside = Path(d) / "outside"
        outside.mkdir()
        linked_dir = Path(d) / ".agentic"
        os.symlink(outside, linked_dir)  # .agentic is a symlink to a dir outside
        dest = linked_dir / "config.yml"
        rc = cli.main(["init", "--profile", "minimal", "--config", str(dest), "--force"])
        check(rc == 1 and not (outside / "config.yml").exists(),
              "init: refuses to write through a symlinked ancestor directory")

    # Same symlinked ancestor, but the outside target file ALREADY exists: --force must not
    # overwrite it (the leaf exists via the symlink, so an exists()-based boundary would miss it).
    with _project_dir() as d:
        outside = Path(d) / "outside"
        outside.mkdir()
        sentinel = outside / "config.yml"
        sentinel.write_text("do-not-clobber\n")
        linked_dir = Path(d) / ".agentic"
        os.symlink(outside, linked_dir)
        dest = linked_dir / "config.yml"  # exists as a real file via the symlinked parent
        rc = cli.main(["init", "--profile", "minimal", "--config", str(dest), "--force"])
        check(rc == 1 and sentinel.read_text() == "do-not-clobber\n",
              "init: refuses to overwrite an existing outside file via a symlinked ancestor (--force)")

    # Symlinked ancestor with an existing subdirectory below it: `.agentic` -> outside, outside/nested/
    # exists, dest = .agentic/nested/config.yml. An is_dir() boundary would stop at nested (following
    # the symlink) and never inspect `.agentic`; every component must be checked.
    with _project_dir() as d:
        outside = Path(d) / "outside"
        (outside / "nested").mkdir(parents=True)
        linked_dir = Path(d) / ".agentic"
        os.symlink(outside, linked_dir)
        dest = linked_dir / "nested" / "config.yml"
        rc = cli.main(["init", "--profile", "minimal", "--config", str(dest), "--force"])
        check(rc == 1 and not (outside / "nested" / "config.yml").exists(),
              "init: refuses a symlinked ancestor even when a real subdir exists below it")

    # A `..` AFTER a symlink must not slip past the guard: `link/../config.yml` normalizes lexically
    # to just `config.yml`, but the filesystem follows `link` first, so the write lands outside.
    with _project_dir() as d:
        (Path(d) / "outside" / "nested").mkdir(parents=True)
        link = Path(d) / "link"
        os.symlink(Path(d) / "outside" / "nested", link)  # link -> outside/nested
        dest = link / ".." / "config.yml"  # follows link, then .. -> outside/config.yml
        rc = cli.main(["init", "--profile", "minimal", "--config", str(dest), "--force"])
        check(rc == 1 and not (Path(d) / "outside" / "config.yml").exists(),
              "init: refuses a symlink followed by '..' (no lexical normalization bypass)")


def test_init_rejects_values_the_pipeline_would_reject() -> None:
    # A free-form value the schema accepts but the renderer rejects (a secret name with a hyphen)
    # must make init fail WITHOUT writing a file, rather than leaving a config that fails doctor.
    from stagr import scaffold
    bad_choices = {**scaffold.default_choices("minimal"), "token_secret": "my-token"}
    original_run_wizard = scaffold.run_wizard
    scaffold.run_wizard = lambda *a, **k: bad_choices  # cmd_init calls this on the TTY path

    class _TTY:
        def isatty(self) -> bool:
            return True
    old_stdin = sys.stdin
    sys.stdin = _TTY()  # type: ignore[assignment]
    try:
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / ".agentic" / "config.yml"
            rc = cli.main(["init", "--config", str(dest)])
            check(rc == 1 and not dest.exists(),
                  "init: an invalid secret name is rejected and no file is written")
        # --print must validate too (before the early return), so a redirected --print never emits
        # an invalid config; stdout stays empty on rejection.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc_print = cli.main(["init", "--print"])
        check(rc_print == 1 and buf.getvalue() == "",
              "init --print: an invalid value is rejected and nothing is printed")
    finally:
        sys.stdin = old_stdin
        scaffold.run_wizard = original_run_wizard


def test_init_rejects_pasted_credential_value() -> None:
    # Pasting a real token VALUE where a secret NAME is expected must be refused before any output,
    # so a live credential is never serialized into the config or --print.
    from stagr import scaffold
    bad_choices = {**scaffold.default_choices("minimal"), "token_secret": "ghp_" + "A" * 24}
    original_run_wizard = scaffold.run_wizard
    scaffold.run_wizard = lambda *a, **k: bad_choices

    class _TTY:
        def isatty(self) -> bool:
            return True
    old_stdin = sys.stdin
    sys.stdin = _TTY()  # type: ignore[assignment]
    try:
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / ".agentic" / "config.yml"
            rc = cli.main(["init", "--config", str(dest)])
            check(rc == 1 and not dest.exists(),
                  "init: a pasted token value is refused and no file is written")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc_print = cli.main(["init", "--print"])
        check(rc_print == 1 and buf.getvalue() == "",
              "init --print: a pasted token value is refused and nothing is printed")
    finally:
        sys.stdin = old_stdin
        scaffold.run_wizard = original_run_wizard


def test_init_reports_write_failure_without_traceback() -> None:
    with _project_dir() as d:
        blocker = Path(d) / "afile"
        blocker.write_text("x")  # a regular file where init expects a parent directory
        dest = blocker / "config.yml"  # mkdir/write_text will raise OSError
        rc = cli.main(["init", "--profile", "minimal", "--config", str(dest)])
        check(rc == 1, "init: a filesystem write failure exits 1 (concise error, no traceback)")
