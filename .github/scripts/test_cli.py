#!/usr/bin/env python3
"""Tests for the M3 operator CLI (doctor / plan / apply).

Runnable with plain `python .github/scripts/test_cli.py` (no pytest). Covers the health
report (secret-by-NAME, no secret values, model resolution, lane selection), fail-loud on an
unresolvable config, and plan/apply determinism + idempotency + prune. Exit 0 = pass.
"""
from __future__ import annotations

import io
import re
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from stagr import cli  # noqa: E402
from stagr import render  # noqa: E402

failures: list[str] = []
SECRET_VALUE = re.compile(r"sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}")


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"OK  {msg}")
    else:
        failures.append(msg)
        print(f"FAIL {msg}", file=sys.stderr)


def test_report() -> None:
    cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    rep = cli.collect_report(cfg, "github")
    check(rep["profile"] == "custom" and rep["default_branch"] == "main", "doctor: platform basics")
    ids = {s["id"] for s in rep["stages"]}
    check({"implement-claude", "implement-codex", "review", "security"} <= ids, "doctor: stages present")
    # claude implementer (claude-code-action) resolves a real model; codex stages are app-supplied.
    impl = next(s for s in rep["stages"] if s["id"] == "implement-claude")
    check(impl["model"] == "claude-sonnet-5", "doctor: claude implementer model resolved")
    codex = next(s for s in rep["stages"] if s["id"] == "implement-codex")
    check("app-supplied" in str(codex["model"]), "doctor: codex implementer model is app-supplied")
    # secret NAMES surfaced, never values.
    check("ANTHROPIC_API_KEY" in rep["secret_names"], "doctor: claude key secret NAME surfaced")
    check("OPENAI_API_KEY" in rep["secret_names"], "doctor: openai key secret NAME surfaced")
    check("CODEX_REMEDIATION_TOKEN" in rep["secret_names"], "doctor: codex review PAT NAME surfaced")
    check("request-review.yml" in rep["workflows"], "doctor: review lane in render set")
    check(not rep["problems"], "doctor: healthy config has no problems")


def test_doctor_no_secret_values_and_exit() -> None:
    # doctor over the dogfood config prints only NAMES, never a secret value; exits 0.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["doctor", "--config", str(REPO_ROOT / ".agentic" / "config.yml")])
    out = buf.getvalue()
    check(rc == 0, "doctor: healthy config exits 0")
    check(SECRET_VALUE.search(out) is None, "doctor: prints no secret value")
    check("CODEX_REMEDIATION_TOKEN" in out, "doctor: prints the secret NAME")


def test_doctor_fail_loud() -> None:
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "config.yml"
        bad.write_text(
            "version: 2\nprofile: custom\n"
            "platform: {type: github, default_branch: main}\n"
            "defaults: {provider: openai, models: {}}\n"
            "stages:\n  - {id: implement, type: implement, backend: {name: generic}}\n"
        )
        rc = cli.main(["doctor", "--config", str(bad), "--json"])
        check(rc == 1, "doctor: unresolvable generic implementer model exits 1")


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


def main() -> int:
    test_report()
    test_doctor_no_secret_values_and_exit()
    test_doctor_fail_loud()
    test_plan_apply_idempotent()
    if failures:
        print(f"\n{len(failures)} test failure(s).", file=sys.stderr)
        return 1
    print("\nAll M3 CLI tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
