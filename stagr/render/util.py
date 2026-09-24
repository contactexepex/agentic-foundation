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
