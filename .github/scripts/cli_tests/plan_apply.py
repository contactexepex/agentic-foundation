"""plan/apply determinism, idempotency, and prune tests."""
from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from .harness import REPO_ROOT, check, cli


def test_plan_apply_idempotent() -> None:
    config = REPO_ROOT / ".agentic" / "config.yml"
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "workflows"
        # plan against an empty target: everything is new, nothing written.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["plan", "--config", str(config), "--out", str(out)])
        check(rc == 0 and "+ new" in buf.getvalue(), "plan: new workflows reported")
        check(not out.exists() or not any(out.iterdir()), "plan: writes nothing")

        # apply writes them.
        rc = cli.main(["apply", "--config", str(config), "--out", str(out)])
        written = sorted(p.name for p in out.glob("*.yml"))
        check(rc == 0 and "validate.yml" in written and "request-review.yml" in written, "apply: writes workflows")

        # second apply is idempotent: nothing changes.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["apply", "--config", str(config), "--out", str(out)])
        check(rc == 0 and "written, " in buf.getvalue() and "0 file(s) written" in buf.getvalue(),
              "apply: second run writes nothing (idempotent)")

        # a hand-written workflow is kept by default, pruned with --prune.
        (out / "custom-hand-written.yml").write_text("name: keep me\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["apply", "--config", str(config), "--out", str(out)])
        check((out / "custom-hand-written.yml").exists(), "apply: orphan kept without --prune")
        cli.main(["apply", "--config", str(config), "--out", str(out), "--prune"])
        check(not (out / "custom-hand-written.yml").exists(), "apply: orphan removed with --prune")
