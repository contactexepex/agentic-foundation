"""Build-preset detection — infer a `build.preset` from a repo's top-level marker files."""
from __future__ import annotations

import json
from pathlib import Path


def _schema_build_presets() -> tuple[str, ...]:
    """The valid `build.preset` values, read from the packaged schema (single source of truth).

    Deriving them here keeps the wizard's offered choices and validation in lockstep with the
    schema, so a mistyped preset can't produce a config that then fails `stagr doctor`.
    """
    schema = json.loads((Path(__file__).resolve().parent.parent / "config.schema.json").read_text(encoding="utf-8"))
    return tuple(schema["properties"]["build"]["properties"]["preset"]["enum"])


BUILD_PRESETS = _schema_build_presets()
_BUILD_PRESET_OPTIONS = " | ".join(BUILD_PRESETS)

# The toolchain-agnostic preset: the fallback when no build marker is recognized. Also the schema's
# own default, so a detected `custom` means "you fill in the commands yourself".
CUSTOM_PRESET = "custom"

# Top-level repo markers that select a build preset, in precedence order (first match wins, so a repo
# carrying several markers resolves deterministically). A preset is chosen ONLY when the repo carries
# the marker its build commands actually need — an npm lockfile for `npm ci`, a Gradle wrapper for
# `./gradlew`, a requirements file for `pip install -r requirements.txt` — so a detected preset always
# renders a Validate workflow that can run. A repo missing that marker (e.g. a package.json with no
# lockfile, or a pyproject-only project) falls back to `CUSTOM_PRESET`, so `init` proposes a safe empty
# default rather than a preset whose commands would fail before lint or tests. (`maven`/`go`/`rust`/
# `dotnet` need only their manifest — those toolchains are provided by the runner.)
_PRESET_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("python", ("requirements.txt",)),
    ("maven", ("pom.xml",)),
    ("gradle", ("gradlew",)),
    ("node", ("package-lock.json", "npm-shrinkwrap.json")),
    ("go", ("go.mod",)),
    ("rust", ("Cargo.toml",)),
    ("dotnet", ("*.csproj", "*.sln")),
)


def _signal_present(project_root: Path, name_patterns: tuple[str, ...]) -> bool:
    """True if a top-level FILE in `project_root` matches any of these name patterns (literal or glob)."""
    return any(match.is_file() for pattern in name_patterns for match in project_root.glob(pattern))


def detect_build_preset(project_root: Path | None = None) -> str:
    """Infer a `build.preset` from the marker files in `project_root` (default: the CWD).

    Deterministic and offline — it only looks for the top-level marker files in `_PRESET_SIGNALS`,
    reads none of their contents, and never touches the network. Returns the first matching preset,
    or `CUSTOM_PRESET` when nothing recognizable is present. It never raises: a filesystem error
    falls back to `CUSTOM_PRESET`, so `init` proposes a safe default on any repo instead of crashing.
    """
    try:
        root = project_root if project_root is not None else Path.cwd()
        for preset, name_patterns in _PRESET_SIGNALS:
            if _signal_present(root, name_patterns):
                return preset
    except OSError:
        # Path.cwd() itself can raise (deleted/unmounted CWD), as can a glob on an unreadable dir.
        return CUSTOM_PRESET
    return CUSTOM_PRESET
