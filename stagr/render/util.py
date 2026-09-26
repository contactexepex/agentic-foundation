"""Shared helpers: reference/URI/secret regex checks, deep-merge, YAML reading, and
path confinement to the project root."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .errors import RenderError

# A URI reference (scheme://…) as opposed to a local filesystem path. Remote fetch of
# `extends` bases and `skills` sources is not supported by the offline renderer; such
# references are rejected up front rather than mis-handled as local paths.
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


def _is_uri(ref: str) -> bool:
    return bool(_URI_SCHEME.match(ref))


# A git ref is safe to interpolate into our generated workflows as long as it cannot break out of a
# double-quoted YAML scalar or a shell double-quoted string. We therefore reject only the genuinely
# dangerous characters (quotes, backtick, $, backslash, whitespace, control chars, leading '-') and
# allow every other git-valid name (e.g. `release+hotfix`, `release,2026`, `feat/x`) rather than an
# over-strict allowlist. A name with a rejected character fails loud at render time.
_UNSAFE_REF = re.compile(r"""[\s"'`$\\]""")


def _ref_is_safe(ref: str) -> bool:
    return bool(ref) and not ref.startswith("-") and not _UNSAFE_REF.search(ref) and all(ord(c) >= 0x20 for c in ref)
# A GitHub Actions secret name (what may follow `secrets.` in an expression). re.ASCII keeps `\w`
# ASCII-only ([A-Za-z0-9_]); without it `\w` would also match Unicode word characters.
_SECRET_NAME = re.compile(r"^[A-Za-z_]\w*$", re.ASCII)
# A model id safe to embed in a GitHub expression string literal (no quotes/metacharacters).
_MODEL_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")

# ----------------------------------------------------------------------------- safe workflow literals
# GitHub Actions evaluates `${{ ... }}` expressions inside workflow-level `env:` and `if:` values before
# the shell runs. Any operator-controlled string templated into such a position must therefore never
# carry the expression opener, or a config value like "${{ secrets.X }}" would be evaluated by the
# runner (e.g. blanking the human-merge label so no PR can match it, or interpolating a secret). GitHub
# has exactly ONE expression syntax, so rejecting the literal opener is complete for this class — and it
# does NOT ban braces on their own, because globs legitimately use `{a,b}` brace-expansion. These are the
# single source of truth for "an operator string that becomes a workflow literal"; every such value in
# `build_context` passes through one of them (see the render_tests closure check).
_GHA_EXPRESSION = "${{"


def _has_gha_expression(value: str) -> bool:
    return _GHA_EXPRESSION in value


def _has_control_char(value: str) -> bool:
    return any(ord(ch) < 0x20 for ch in value)


def assert_safe_label(value: str, field: str) -> str:
    """A GitHub label templated into a double-quoted YAML scalar and a jq `--arg`. Reject an empty label
    (it could match no PR, silently disabling a hard stop) and any value that could break the scalar
    (`"`, backslash), inject a GitHub expression (`${{`), or carry a control character."""
    if not value:
        raise RenderError(
            f"{field} must not be empty — no GitHub label could match, so the human-merge hard stop "
            "could never pause a PR for human review."
        )
    if '"' in value or "'" in value or "\\" in value or _has_control_char(value) or _has_gha_expression(value):
        raise RenderError(
            f"{field} {value!r} contains a double quote, single quote, backslash, control character, "
            f"or the GitHub expression opener {_GHA_EXPRESSION!r}, and cannot be safely templated into "
            "the workflow; use a plain label name."
        )
    return value


def assert_safe_check_name(value: str, field: str) -> str:
    """An external check name templated into a single-quoted JSON env value and matched with jq. Reject
    empty, a single quote (breaks the JSON env scalar), a control character, or a GitHub expression."""
    if not value:
        raise RenderError(
            f"{field} contains an empty check name; remove it or use the exact check name your quality "
            "tool publishes (an empty entry would silently gate nothing)."
        )
    if "'" in value or _has_control_char(value) or _has_gha_expression(value):
        raise RenderError(
            f"{field} {value!r} contains a single quote, control character, or the GitHub expression "
            f"opener {_GHA_EXPRESSION!r}, and cannot be safely templated into the workflow; use the exact "
            "check name your quality tool publishes."
        )
    return value


def assert_safe_glob(value: str, field: str) -> str:
    """A fast-path glob templated (JSON-encoded) into a workflow env value parsed by jq. Reject empty, a
    control character, or a GitHub expression — but allow braces so `**/*.{js,ts}` brace-expansion works."""
    if not value:
        raise RenderError(f"{field} contains an empty glob; remove it or use a real pattern.")
    if _has_control_char(value) or _has_gha_expression(value):
        raise RenderError(
            f"{field} {value!r} contains a control character or the GitHub expression opener "
            f"{_GHA_EXPRESSION!r}; use a plain glob pattern (brace-expansion like '**/*.{{js,ts}}' is fine)."
        )
    return value


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge overlay onto base (overlay wins). Lists/scalars are replaced."""
    merged = dict(base)
    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            merged[key] = _deep_merge(base_value, overlay_value)
        else:
            merged[key] = overlay_value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        # UTF-8 explicitly: generated configs are written UTF-8 (em dashes, box-drawing), so reading
        # them back must not depend on a non-UTF-8 locale encoding (e.g. Windows CP932).
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RenderError(f"file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise RenderError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RenderError(f"{path} must be a mapping")
    return data


def _confine_to_project_root(path: Path, what: str) -> Path:
    """Resolve `path` and reject anything outside the project root (the CWD); return it resolved.

    stagr is a control plane that operates on the current repository, so every path it reads or
    writes — the `--config` contract, its `extends` bases, the file `init` scaffolds — must live
    inside that checkout. A value resolving outside it (`../../etc/passwd`, an absolute host path,
    or a symlink escape — `.resolve()` follows symlinks) is either a mistake or, in an agentic flow
    where these values can be steered by untrusted data, an attempt to read or clobber an arbitrary
    host file. Reject it, the same containment the toolkit applies to skill/preset/instruction paths
    (see `_load_agent_preset` and `backends/generic/runner._confine`).
    """
    root = Path.cwd().resolve()
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        # An untrusted checkout can contain a symlink loop (a -> b -> a) in the path chain, which
        # makes Path.resolve() raise RuntimeError (or OSError). Turn any resolution failure into a
        # clean RenderError so callers report it, rather than crashing with a traceback.
        raise RenderError(f"{what} '{path}' cannot be resolved: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise RenderError(
            f"{what} '{path}' resolves outside the project root ({root}); "
            "run stagr from your repository with the file inside it"
        )
    return resolved


def confine_config_path(path: Path) -> Path:
    """Confine a CLI-supplied `--config` path to the project root; see `_confine_to_project_root`."""
    return _confine_to_project_root(path, "config path")
