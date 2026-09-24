#!/usr/bin/env python3
"""Tests for the M3 operator CLI (doctor / plan / apply).

Runnable with plain `python .github/scripts/test_cli.py` (no pytest). Covers the health
report (secret-by-NAME, no secret values, model resolution, lane selection), fail-loud on an
unresolvable config, and plan/apply determinism + idempotency + prune. Exit 0 = pass.
"""
from __future__ import annotations

import io
import os
import re
import sys
import tempfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from stagr import cli  # noqa: E402
from stagr import render  # noqa: E402

failures: list[str] = []
SECRET_VALUE = re.compile(r"sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}")


@contextmanager
def _project_dir():
    """A temp dir that is also the CWD for the block.

    stagr confines the config file, its extends bases, and init's write destination to the project
    root (the CWD), so a test that exercises those write/read paths must run from inside a project
    checkout (a real operator runs stagr from their repo).
    """
    prev = Path.cwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            yield Path(d)
        finally:
            os.chdir(prev)


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
    # implement-codex is a disabled roadmap stage (Codex implementer not rendered yet), so it is
    # dropped from the expanded graph; the active stages are the Claude implementer + Codex reviewers.
    check({"implement-claude", "review", "security"} <= ids, "doctor: stages present")
    check("implement-codex" not in ids, "doctor: disabled roadmap codex implementer is dropped")
    # anthropic implementer (Claude Code) resolves a real model; codex stages are app-supplied.
    impl = next(s for s in rep["stages"] if s["id"] == "implement-claude")
    check(impl["model"] == "claude-sonnet-5", "doctor: anthropic implementer model resolved")
    # secret NAMES surfaced, never values. The anthropic implementer (Claude Code) needs
    # ANTHROPIC_API_KEY; the openai stages run via the Codex app, so OPENAI_API_KEY is NOT
    # required (the app does not read a provider API key); the codex review lane needs the PAT.
    check("ANTHROPIC_API_KEY" in rep["secret_names"], "doctor: anthropic key secret NAME surfaced")
    check("OPENAI_API_KEY" not in rep["secret_names"],
          "doctor: openai key NOT required when openai is used only via the codex app backend")
    check("REMEDIATION_TOKEN" in rep["secret_names"], "doctor: codex review PAT NAME surfaced")
    check("request-review.yml" in rep["workflows"], "doctor: review lane in render set")
    check(not rep["problems"], "doctor: healthy config has no problems")

    # An anthropic implement stage (Claude Code) requires the provider key and renders cleanly.
    anthro_cfg = {"version": 2, "profile": "custom",
                  "platform": {"type": "github", "default_branch": "main"},
                  "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "m"}}},
                  "stages": [{"id": "impl", "type": "implement", "provider": "anthropic"}]}
    rep_anthro = cli.collect_report(anthro_cfg, "github")
    check("ANTHROPIC_API_KEY" in rep_anthro["secret_names"],
          "doctor: anthropic key IS required for the Claude implementer")
    check(not rep_anthro["problems"], "doctor: anthropic implement config is healthy")

    # A codex review stage WITHOUT pr_updated renders no push-review lane, so doctor must NOT ask for
    # the review PAT — the secret predicate mirrors lane selection.
    no_push_cfg = {"version": 2, "profile": "custom",
                   "platform": {"type": "github", "default_branch": "main"},
                   "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "m"}}},
                   "stages": [{"id": "review", "type": "review", "provider": "openai", "triggers": ["pr_opened"]}]}
    rep_no_push = cli.collect_report(no_push_cfg, "github")
    check("REMEDIATION_TOKEN" not in rep_no_push["secret_names"],
          "doctor: no review PAT required when no push-review lane renders")


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
    with _project_dir() as d:
        bad = d / "config.yml"
        bad.write_text(
            "version: 2\nprofile: custom\n"
            "platform: {type: github, default_branch: main}\n"
            "defaults: {provider: openai, models: {}}\n"
            "stages:\n  - {id: implement, type: implement, backend: {name: generic}}\n"
        )
        # The config sits inside the project root the CLI confines `--config` to, so this exercises
        # the model-resolution failure (not the containment guard).
        rc = cli.main(["doctor", "--config", "config.yml", "--json"])
        check(rc == 1, "doctor: unresolvable generic implementer model exits 1")


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
    with _project_dir() as d:
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


def test_init_next_steps_carry_custom_config_path() -> None:
    with _project_dir() as d:
        dest = Path(d) / "config files" / "stagr.yml"  # a space: no shell-specific quoting is emitted
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["init", "--profile", "minimal", "--config", str(dest)])
        out = buf.getvalue()
        check(rc == 0 and dest.exists(), "init: writes to a custom --config path")
        check(str(dest) in out and "--config" in out,
              "init: next-steps points at the custom config path (shell-neutral, path shown plainly)")


def test_init_writes_utf8() -> None:
    with _project_dir() as d:
        dest = Path(d) / ".agentic" / "config.yml"
        rc = cli.main(["init", "--profile", "standard", "--config", str(dest)])
        raw = dest.read_bytes()
        check(rc == 0 and "—".encode("utf-8") in raw,
              "init: generated file is written UTF-8 (em dash encodes regardless of locale)")


def test_init_reports_write_failure_without_traceback() -> None:
    with _project_dir() as d:
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


def test_detect_build_preset() -> None:
    from stagr import scaffold
    # Each preset is selected only by the marker its build commands actually need (conservative).
    marker_to_preset = {
        "requirements.txt": "python",
        "pom.xml": "maven", "gradlew": "gradle",
        "package-lock.json": "node", "npm-shrinkwrap.json": "node",
        "go.mod": "go", "Cargo.toml": "rust",
        "App.csproj": "dotnet", "Solution.sln": "dotnet",
    }
    for marker, expected in marker_to_preset.items():
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / marker).write_text("x")
            got = scaffold.detect_build_preset(Path(d))
            check(got == expected, f"detect: {marker} -> {expected} (got {got})")

    # A toolchain marker WITHOUT the file its commands need -> custom (never a preset that would fail):
    # a package.json with no lockfile (npm ci), a pyproject/setup.py with no requirements file, a
    # Gradle build script with no wrapper.
    for lonely in ("package.json", "pyproject.toml", "setup.py", "build.gradle", "build.gradle.kts"):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / lonely).write_text("x")
            check(scaffold.detect_build_preset(Path(d)) == scaffold.CUSTOM_PRESET,
                  f"detect: {lonely} without its build marker -> custom (conservative)")

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "README.md").write_text("x")
        check(scaffold.detect_build_preset(Path(d)) == scaffold.CUSTOM_PRESET,
              "detect: an unrecognized repo -> custom")
        check(scaffold.detect_build_preset(Path(d) / "gone") == scaffold.CUSTOM_PRESET,
              "detect: a missing directory -> custom (never raises)")

    # precedence is deterministic when several markers coexist (python precedes node).
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "requirements.txt").write_text("x")
        (Path(d) / "package-lock.json").write_text("x")
        check(scaffold.detect_build_preset(Path(d)) == "python",
              "detect: precedence is deterministic (python before node)")

    # only FILES are signals — a directory named like a marker is ignored.
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "go.mod").mkdir()
        check(scaffold.detect_build_preset(Path(d)) == scaffold.CUSTOM_PRESET,
              "detect: a directory named like a marker is not a signal")


def test_detect_presets_are_schema_valid() -> None:
    from stagr import scaffold
    signal_presets = {preset for preset, _ in scaffold._PRESET_SIGNALS}
    check(signal_presets <= set(scaffold.BUILD_PRESETS),
          "detect: every signal preset is a valid schema build.preset (no drift)")
    check(scaffold.CUSTOM_PRESET in scaffold.BUILD_PRESETS,
          "detect: CUSTOM_PRESET is a valid schema build.preset")


def test_init_uses_detected_preset() -> None:
    # init proposes the repo's detected toolchain (non-interactive path), falling back to custom.
    with _project_dir() as d:
        (d / "go.mod").write_text("module example\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["init", "--profile", "minimal", "--print"])
        check(rc == 0 and "preset: go" in buf.getvalue(),
              "init --profile: uses the detected build preset (go)")
    with _project_dir() as d:
        (d / "README.md").write_text("x\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["init", "--profile", "minimal", "--print"])
        check(rc == 0 and "preset: custom" in buf.getvalue(),
              "init --profile: falls back to custom on an unrecognized repo")


def test_init_wizard_uses_detected_preset_default() -> None:
    from stagr import scaffold
    with _project_dir() as d:
        (d / "Cargo.toml").write_text("[package]\n")
        answers = iter([""] * 12)  # Enter throughout accepts the autodetected default
        ch = scaffold.run_wizard(read_input=lambda _p: next(answers), write_line=lambda _m: None)
        check(ch["build_preset"] == "rust",
              "wizard: pressing Enter accepts the autodetected preset (rust)")


def main() -> int:
    test_report()
    test_doctor_no_secret_values_and_exit()
    test_doctor_fail_loud()
    test_config_path_confined_to_project_root()
    test_config_path_symlink_loop_is_clean_error()
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
    test_detect_build_preset()
    test_detect_presets_are_schema_valid()
    test_init_uses_detected_preset()
    test_init_wizard_uses_detected_preset_default()
    if failures:
        print(f"\n{len(failures)} test failure(s).", file=sys.stderr)
        return 1
    print("\nAll M3 CLI tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
