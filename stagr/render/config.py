"""Config loading and validation: resolve `extends` bases, load the contract, validate it
against the JSON Schema, and run the semantic checks the schema cannot express."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .constants import PROVIDER_ANTHROPIC, RENAMED_ANTHROPIC_PROVIDER, SCHEMA_PATH
from .errors import RenderError
from .lanes import _ensure_auto_merge_coherent, _ensure_supported_review_graph
from .stages import expand_stages
from .util import _confine_to_project_root, _deep_merge, _is_uri, _read_yaml


def resolve_extends(cfg: dict[str, Any], base_dir: Path, _seen: set[str] | None = None) -> dict[str, Any]:
    """Merge `extends` base config(s) before this file (local values win).

    Bases are resolved relative to `base_dir`. `uri:`-style remote bases are not
    fetched here — a base that is not a readable local path fails loudly.
    """
    ext = cfg.get("extends")
    if not ext:
        return cfg
    # Only a string or a list of strings is a valid `extends`. A mapping (e.g. {base.yml: ...})
    # would otherwise have its KEYS iterated as base paths, silently inheriting an unintended policy.
    if isinstance(ext, str):
        bases = [ext]
    elif isinstance(ext, list) and all(isinstance(b, str) for b in ext):
        bases = list(ext)
    else:
        raise RenderError("extends must be a string or a list of path strings")
    _seen = _seen or set()
    merged: dict[str, Any] = {}
    for ref in bases:
        if _is_uri(str(ref)):
            raise RenderError(
                f"extends references a URI ('{ref}'), which the offline renderer does not "
                "fetch; vendor the base config locally and reference it by relative path"
            )
        p = _confine_to_project_root(base_dir / ref, f"extends base '{ref}'")
        key = str(p)
        if key in _seen:
            raise RenderError(f"circular extends via {ref}")
        # `_seen` tracks only the CURRENT recursion path (ancestors), so two bases that share a
        # common ancestor (a diamond) do not falsely trip cycle detection; remove after resolving.
        _seen.add(key)
        base = resolve_extends(_read_yaml(p), p.parent, _seen)
        _seen.discard(key)
        merged = _deep_merge(merged, base)
    child = {k: v for k, v in cfg.items() if k != "extends"}
    return _deep_merge(merged, child)


def load_config(path: Path) -> dict[str, Any]:
    cfg = _read_yaml(path)
    return resolve_extends(cfg, path.parent)


def validate_config(cfg: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(cfg), key=lambda err: list(err.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '(root)'}: {error.message}"
            for error in errors
        )
        raise RenderError(f"config does not conform to schema: {details}")
    _validate_semantics(cfg)


def _validate_semantics(cfg: dict[str, Any]) -> None:
    """Contract-shape checks the JSON Schema cannot express, at the front door.

    Rejects the not-yet-supported `source: uri` skill registry entries loudly here (rather
    than deferring to a backend-time error), so a config that names a remote skill fails at
    validation with a clear "vendor locally" message. Remote fetch is tracked as future work.
    """
    for sid, entry in (cfg.get("skills", {}) or {}).items():
        if isinstance(entry, dict) and entry.get("source") == "uri":
            raise RenderError(
                f"skill '{sid}' uses source: uri, which the offline renderer does not fetch; "
                "vendor it locally and use source: path (remote fetch is future work)"
            )

    # The Anthropic provider id was renamed `claude` -> `anthropic`. Reject the old id with a clear
    # migration message rather than let it fall through to a wrong default key secret (MODEL_API_KEY)
    # while the pipeline is reported healthy.
    providers_in_use = [(cfg.get("defaults", {}) or {}).get("provider")]
    providers_in_use += [(stage or {}).get("provider") for stage in (cfg.get("stages", []) or [])]
    if RENAMED_ANTHROPIC_PROVIDER in providers_in_use:
        raise RenderError(
            f"provider '{RENAMED_ANTHROPIC_PROVIDER}' was renamed to '{PROVIDER_ANTHROPIC}'; update "
            f"defaults.provider / stages[].provider (and defaults.models.{RENAMED_ANTHROPIC_PROVIDER} "
            f"-> defaults.models.{PROVIDER_ANTHROPIC}) to '{PROVIDER_ANTHROPIC}'."
        )

    # A Codex security lane that no event can ever satisfy (security stage without a code-review
    # stage) is rejected here at the front door, not left to render a dead workflow.
    expanded = expand_stages(cfg)
    _ensure_supported_review_graph(expanded)
    # An auto-merge gate whose Codex-review requirement could never be met (fast path on, or a blocking
    # review that skips pushed heads) would deadlock silently — reject it at the front door too.
    _ensure_auto_merge_coherent(expanded, cfg)

    # Templating safety: building the context runs every safe-literal validator (rejecting a ${{ }}
    # expression / breakout char in a label, external-check name, glob, branch, secret name, or model,
    # and an invalid app_id / protected path). Run it here so `stagr validate` — the front door — catches
    # these, not only `render`. We only want the validation side effect.
    from .context import build_context

    build_context(cfg)
