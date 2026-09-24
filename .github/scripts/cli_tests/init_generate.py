"""init generation/wizard tests: profiles, formatting, gates, and stdout hygiene."""
from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from .harness import REPO_ROOT, _project_dir, check, cli, render


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
