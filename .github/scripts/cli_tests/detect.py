"""Build-preset detection tests + init use of the detected preset."""
from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from .harness import _project_dir, check, cli, render


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
