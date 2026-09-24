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
    # secret NAMES surfaced, never values. The claude implementer (generic-family backend) needs
    # ANTHROPIC_API_KEY; the openai stages are all codex (app) backend, so OPENAI_API_KEY is NOT
    # required (the app does not read a provider API key); the codex review lane needs the PAT.
    check("ANTHROPIC_API_KEY" in rep["secret_names"], "doctor: claude key secret NAME surfaced")
    check("OPENAI_API_KEY" not in rep["secret_names"],
          "doctor: openai key NOT required when openai is used only via the codex app backend")
    check("REMEDIATION_TOKEN" in rep["secret_names"], "doctor: codex review PAT NAME surfaced")
    check("request-review.yml" in rep["workflows"], "doctor: review lane in render set")
    check(not rep["problems"], "doctor: healthy config has no problems")

    # A model-consuming (generic) backend on openai DOES require the provider key.
    generic_cfg = {"version": 2, "profile": "custom",
                   "platform": {"type": "github", "default_branch": "main"},
                   "defaults": {"provider": "openai", "models": {"openai": {"default": "m"}}},
                   "stages": [{"id": "impl", "type": "implement", "backend": {"name": "generic"}}]}
    rep_generic = cli.collect_report(generic_cfg, "github")
    check("OPENAI_API_KEY" in rep_generic["secret_names"],
          "doctor: openai key IS required for a model-consuming (generic) backend")


def test_doctor_no_secret_values_and_exit() -> None:
    # doctor over the dogfood config prints only NAMES, never a secret value; exits 0.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["doctor", "--config", str(REPO_ROOT / ".agentic" / "config.yml")])
    out = buf.getvalue()
    check(rc == 0, "doctor: healthy config exits 0")
    check(SECRET_VALUE.search(out) is None, "doctor: prints no secret value")
    check("REMEDIATION_TOKEN" in out, "doctor: prints the secret NAME")


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


def test_init_profiles_generate_valid_configs() -> None:
    from stagr import scaffold
    for prof in scaffold.PROFILES:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["init", "--profile", prof, "--print"])
        text = buf.getvalue()
        check(rc == 0, f"init --profile {prof} --print exits 0")
        check("REMEDIATION_TOKEN" in text, f"init {prof}: uses the default token name")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".agentic" / "config.yml"
            p.parent.mkdir(parents=True)
            p.write_text(text)
            cfg = render.load_config(p)
            render.validate_config(cfg)
            render.render_all(cfg, "github")
        check(True, f"init {prof}: generated config validates and renders")


def test_init_write_and_overwrite_guard() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / ".agentic" / "config.yml"
        rc = cli.main(["init", "--profile", "minimal", "--config", str(dest)])
        check(rc == 0 and dest.exists(), "init: writes the config file")
        rc2 = cli.main(["init", "--profile", "minimal", "--config", str(dest)])
        check(rc2 == 1, "init: refuses to overwrite an existing file without --force")
        rc3 = cli.main(["init", "--profile", "minimal", "--config", str(dest), "--force"])
        check(rc3 == 0, "init: --force overwrites")


def test_init_wizard_defaults_and_nontty() -> None:
    from stagr import scaffold
    answers = iter([""] * 12)  # Enter throughout accepts every default
    ch = scaffold.run_wizard(read_input=lambda _p: next(answers), write_line=lambda _m: None)
    check(ch["profile"] == "standard" and ch["token_secret"] == "REMEDIATION_TOKEN",
          "wizard: pressing Enter accepts the defaults")

    # No --profile and a non-interactive stdin must fail fast (never block waiting on input).
    class _NoTTY:
        def isatty(self) -> bool:
            return False
    old = sys.stdin
    sys.stdin = _NoTTY()  # type: ignore[assignment]
    try:
        rc = cli.main(["init"])
    finally:
        sys.stdin = old
    check(rc == 1, "init: no --profile on a non-terminal exits 1 (does not hang)")


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


def test_init_escapes_test_command() -> None:
    from stagr import scaffold
    ch = scaffold.default_choices("minimal")
    ch["build_test"] = 'python -c "print(1)"'  # embedded quotes must not break the YAML
    text = scaffold.generate(ch)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.yml"
        p.write_text(text)
        cfg = render.load_config(p)
        render.validate_config(cfg)
    check(cfg["build"]["commands"]["test"] == 'python -c "print(1)"',
          "init: a test command with quotes is emitted as a valid YAML scalar")


def test_init_refuses_symlink_destination() -> None:
    import os
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "outside.yml"
        link = Path(d) / "config.yml"
        os.symlink(target, link)  # broken symlink (target does not exist)
        rc = cli.main(["init", "--profile", "minimal", "--config", str(link), "--force"])
        check(rc == 1 and not target.exists(),
              "init: refuses to write through a symlink destination (even with --force)")

    # A symlinked ANCESTOR (e.g. `.agentic` -> outside the checkout) must also be refused: the
    # leaf itself is not a symlink, but writing would follow the parent and escape.
    with tempfile.TemporaryDirectory() as d:
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
    with tempfile.TemporaryDirectory() as d:
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
    with tempfile.TemporaryDirectory() as d:
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
    with tempfile.TemporaryDirectory() as d:
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


def test_init_next_steps_carry_custom_config_path() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "config files" / "stagr.yml"  # a space: no shell-specific quoting is emitted
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["init", "--profile", "minimal", "--config", str(dest)])
        out = buf.getvalue()
        check(rc == 0 and dest.exists(), "init: writes to a custom --config path")
        check(str(dest) in out and "--config" in out,
              "init: next-steps points at the custom config path (shell-neutral, path shown plainly)")


def test_init_writes_utf8() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / ".agentic" / "config.yml"
        rc = cli.main(["init", "--profile", "standard", "--config", str(dest)])
        raw = dest.read_bytes()
        check(rc == 0 and "—".encode("utf-8") in raw,
              "init: generated file is written UTF-8 (em dash encodes regardless of locale)")


def test_init_reports_write_failure_without_traceback() -> None:
    with tempfile.TemporaryDirectory() as d:
        blocker = Path(d) / "afile"
        blocker.write_text("x")  # a regular file where init expects a parent directory
        dest = blocker / "config.yml"  # mkdir/write_text will raise OSError
        rc = cli.main(["init", "--profile", "minimal", "--config", str(dest)])
        check(rc == 1, "init: a filesystem write failure exits 1 (concise error, no traceback)")


def test_init_print_keeps_stdout_yaml_only() -> None:
    # Interactive stdin + redirected stdout (`stagr init --print > .agentic/config.yml`): the
    # wizard's UI must go to stderr and validation must run, so stdout is pure, valid YAML.
    import yaml as _yaml

    class _TTYStdin:
        def isatty(self) -> bool:
            return True

        def readline(self) -> str:
            return "\n"  # accept every default
    old_stdin = sys.stdin
    sys.stdin = _TTYStdin()  # type: ignore[assignment]
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = cli.main(["init", "--print"])
    finally:
        sys.stdin = old_stdin
    out = buf.getvalue()
    check(rc == 0, "init --print (wizard, all defaults): exits 0")
    check("── Scope ──" not in out and "Press Enter" not in out,
          "init --print: wizard UI is kept off stdout")
    parsed = None
    try:
        parsed = _yaml.safe_load(out)
    except _yaml.YAMLError:
        parsed = None
    check(isinstance(parsed, dict) and parsed.get("version") == 2,
          "init --print: stdout is valid YAML only")


def test_init_full_profile_keeps_security_blocking() -> None:
    from stagr import scaffold
    text = scaffold.generate(scaffold.default_choices("full"))
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.yml"
        p.write_text(text)
        cfg = render.load_config(p)
        render.validate_config(cfg)
    sec = next(s for s in cfg["stages"] if s.get("type") == "security")
    check(sec.get("gate") == render.GATE_BLOCKING,
          "init --profile full: security stage stays blocking (matches canonical profile)")
    # `standard` derives advisory security from the same source of truth.
    std = scaffold.generate(scaffold.default_choices("standard"))
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.yml"
        p.write_text(std)
        cfg2 = render.load_config(p)
    sec2 = next(s for s in cfg2["stages"] if s.get("type") == "security")
    check(sec2.get("gate") == render.GATE_ADVISORY,
          "init --profile standard: security stage is advisory (matches canonical profile)")


def test_init_review_gate_derived_from_profile() -> None:
    from stagr import scaffold
    expected = {"minimal": render.GATE_ADVISORY, "standard": render.GATE_BLOCKING,
                "full": render.GATE_BLOCKING}
    for prof, want in expected.items():
        text = scaffold.generate(scaffold.default_choices(prof))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.yml"
            p.write_text(text)
            cfg = render.load_config(p)
            render.validate_config(cfg)
        review = next(s for s in cfg["stages"] if s.get("type") == "review")
        check(review.get("gate") == want,
              f"init --profile {prof}: review gate is {want} (matches canonical profile)")


def test_init_quotes_yaml_keyword_scalars() -> None:
    from stagr import scaffold
    ch = scaffold.default_choices("minimal")
    ch["default_branch"] = "on"  # a valid branch name YAML would otherwise read as boolean True
    text = scaffold.generate(ch)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.yml"
        p.write_text(text)
        cfg = render.load_config(p)
        render.validate_config(cfg)
    check(cfg["platform"]["default_branch"] == "on",
          "init: a YAML-keyword default branch ('on') is emitted as a quoted string, not a bool")


def test_init_wizard_governance_unrecognized_keeps_profile_default() -> None:
    from stagr import scaffold
    # profile=full (blocking security), then an unrecognized governance answer must NOT downgrade it.
    answers = iter(["full", "", "", "", "", "", "ye"])  # profile,branch,model,token,preset,test,gov
    ch = scaffold.run_wizard(read_input=lambda _p: next(answers), write_line=lambda _m: None)
    check(ch["security_blocking"] is True,
          "wizard: an unrecognized governance answer keeps the full profile's blocking default")


def test_init_build_presets_match_schema_and_wizard_validates() -> None:
    import json as _json
    from stagr import scaffold
    schema = _json.loads((REPO_ROOT / "stagr" / "config.schema.json").read_text())
    schema_presets = set(schema["properties"]["build"]["properties"]["preset"]["enum"])
    check(set(scaffold.BUILD_PRESETS) == schema_presets,
          "init: BUILD_PRESETS matches the schema's build.preset enum (no drift)")

    # A mistyped preset in the wizard falls back to a schema-valid value, so the generated
    # config still passes doctor rather than emitting `preset: pyhton`.
    answers = iter(["", "", "", "", "pyhton", "", "n"])  # profile,branch,model,token,preset,test,gov
    ch = scaffold.run_wizard(read_input=lambda _p: next(answers), write_line=lambda _m: None)
    check(ch["build_preset"] == "custom",
          "wizard: an unknown build preset falls back to 'custom'")
    text = scaffold.generate(ch)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.yml"
        p.write_text(text)
        cfg = render.load_config(p)
        render.validate_config(cfg)
    check(cfg["build"]["preset"] in schema_presets,
          "wizard: generated build preset is schema-valid after fallback")


def test_default_token_secret_is_neutral() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.yml"
        p.write_text(
            "version: 2\nprofile: custom\n"
            "platform: {type: github, default_branch: main}\n"
            "defaults: {provider: openai, models: {}}\n"
            "stages:\n  - {id: review, type: review, provider: openai, backend: {name: codex}}\n"
        )
        rep = cli.collect_report(render.load_config(p), "github")
        check("REMEDIATION_TOKEN" in rep["secret_names"],
              "default review PAT secret NAME is REMEDIATION_TOKEN when auth.token_secret is omitted")


def main() -> int:
    test_report()
    test_doctor_no_secret_values_and_exit()
    test_doctor_fail_loud()
    test_plan_apply_idempotent()
    test_init_profiles_generate_valid_configs()
    test_init_write_and_overwrite_guard()
    test_init_wizard_defaults_and_nontty()
    test_help_command()
    test_init_escapes_test_command()
    test_init_refuses_symlink_destination()
    test_init_rejects_values_the_pipeline_would_reject()
    test_init_rejects_pasted_credential_value()
    test_init_next_steps_carry_custom_config_path()
    test_init_writes_utf8()
    test_init_reports_write_failure_without_traceback()
    test_init_print_keeps_stdout_yaml_only()
    test_init_full_profile_keeps_security_blocking()
    test_init_review_gate_derived_from_profile()
    test_init_quotes_yaml_keyword_scalars()
    test_init_wizard_governance_unrecognized_keeps_profile_default()
    test_init_build_presets_match_schema_and_wizard_validates()
    test_default_token_secret_is_neutral()
    if failures:
        print(f"\n{len(failures)} test failure(s).", file=sys.stderr)
        return 1
    print("\nAll M3 CLI tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
