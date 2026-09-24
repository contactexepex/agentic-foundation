#!/usr/bin/env python3
"""agentic-foundation — GitHub pipeline renderer (M2).

Reads a repository's `.agentic/config.yml`, resolves it against the contract
(`install/config.schema.json`), and renders the platform pipeline from the
tokenized templates in `templates/workflows/<platform>/` into `.github/workflows/`.

Design notes
------------
- Deterministic: same config + templates -> byte-identical output.
- No network, no secrets. Secrets are referenced by NAME only.
- Provider/model resolution is the reusable core (M3's doctor/plan/apply import it):
  per-stage, per-tier, precedence per-request > stage > org/account default, with
  `models.aliases` expansion, and FAIL-LOUD if nothing resolves (no hidden default).
- `extends`, `from`-presets, and skills-registry resolution happen before rendering so
  the rendered pipeline reflects the fully-merged contract.

CLI:
    python install/render.py --config .agentic/config.yml --out .github/workflows
    python install/render.py --config .agentic/config.yml --print
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "install" / "config.schema.json"
TEMPLATE_ROOT = REPO_ROOT / "templates" / "workflows"
AGENTS_DIR = REPO_ROOT / "templates" / "agents"

GITHUB_ROLE_MAP = {
    "owner": "OWNER",
    "member": "MEMBER",
    "collaborator": "COLLABORATOR",
    "contributor": "CONTRIBUTOR",
}

# Backends that consume a resolved model from the contract. App backends (codex,
# openhands, swe-agent, pr-agent) choose their own model, so resolution is skipped.
BACKENDS_NEEDING_MODEL = {"generic", "claude-code-action"}

# Preset -> default build commands (pre-fill; explicit build.commands override per key).
# Mirrors docs/CONFIGURATION.md "Presets".
PRESET_COMMANDS: dict[str, dict[str, str]] = {
    "python": {"install": "pip install -r requirements.txt", "lint": "ruff check .", "test": "python -m pytest"},
    "maven": {"install": "mvn -q -N install", "lint": "mvn -q spotless:check", "test": "mvn -q verify"},
    "gradle": {"install": "./gradlew dependencies", "lint": "./gradlew check -x test", "test": "./gradlew test"},
    "node": {"install": "npm ci", "lint": "npm run lint", "test": "npm test"},
    "go": {"install": "go mod download", "lint": "golangci-lint run", "test": "go test ./..."},
    "rust": {"install": "cargo fetch", "lint": "cargo clippy -- -D warnings", "test": "cargo test"},
    "dotnet": {"install": "dotnet restore", "lint": "dotnet format --verify-no-changes", "test": "dotnet test"},
    "custom": {},
}

PROFILE_STAGES: dict[str, list[dict[str, Any]]] = {
    "minimal": [
        {"id": "implement", "type": "implement", "gate": "advisory"},
        {"id": "review", "type": "review", "gate": "advisory"},
    ],
    "standard": [
        {"id": "implement", "type": "implement"},
        {"id": "review", "type": "review", "gate": "blocking"},
        {"id": "security", "type": "security", "gate": "advisory"},
    ],
    "full": [
        {"id": "plan", "type": "plan", "gate": "advisory"},
        {"id": "implement", "type": "implement"},
        {"id": "security", "type": "security", "gate": "blocking"},
        {"id": "test", "type": "test", "gate": "blocking"},
        {"id": "integration-test", "type": "integration-test", "gate": "blocking"},
        {"id": "review", "type": "review", "gate": "blocking"},
        {"id": "docs", "type": "docs", "gate": "advisory"},
    ],
    "custom": [],
}


class RenderError(Exception):
    """A configuration/resolution error that must fail loudly."""


# A URI reference (scheme://…) as opposed to a local filesystem path. Remote fetch of
# `extends` bases and `skills` sources is not supported by the offline renderer; such
# references are rejected up front rather than mis-handled as local paths.
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


def _is_uri(ref: str) -> bool:
    return bool(_URI_SCHEME.match(ref))


# --------------------------------------------------------------------------- config


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge overlay onto base (overlay wins). Lists/scalars are replaced."""
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise RenderError(f"file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise RenderError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RenderError(f"{path} must be a mapping")
    return data


def resolve_extends(cfg: dict[str, Any], base_dir: Path, _seen: set[str] | None = None) -> dict[str, Any]:
    """Merge `extends` base config(s) before this file (local values win).

    Bases are resolved relative to `base_dir`. `uri:`-style remote bases are not
    fetched here — a base that is not a readable local path fails loudly.
    """
    ext = cfg.get("extends")
    if not ext:
        return cfg
    bases = [ext] if isinstance(ext, str) else list(ext)
    _seen = _seen or set()
    merged: dict[str, Any] = {}
    for ref in bases:
        if _is_uri(str(ref)):
            raise RenderError(
                f"extends references a URI ('{ref}'), which the offline renderer does not "
                "fetch; vendor the base config locally and reference it by relative path"
            )
        p = (base_dir / ref).resolve()
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
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(cfg), key=lambda e: list(e.path))
    if errors:
        lines = "; ".join(
            f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors
        )
        raise RenderError(f"config does not conform to schema: {lines}")
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


# ------------------------------------------------------------------------- stages


def _load_agent_preset(name: str) -> dict[str, Any]:
    p = AGENTS_DIR / f"{name}.yml"
    if not p.is_file():
        raise RenderError(f"agent preset '{name}' not found at {p}")
    return _read_yaml(p)


def expand_stages(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand `from` presets and merge the profile's stages with explicit stages."""
    profile = cfg.get("profile", "standard")
    if profile not in PROFILE_STAGES:
        raise RenderError(f"unknown profile: {profile}")
    base = {s["id"]: dict(s) for s in PROFILE_STAGES[profile]}
    order = [s["id"] for s in PROFILE_STAGES[profile]]
    explicit_ids: set[str] = set()
    for stage in cfg.get("stages", []) or []:
        sid = stage.get("id")
        if not sid:
            raise RenderError("every stage needs an id")
        # Two explicit stages sharing an id would silently deep-merge into a hybrid stage and drop
        # a graph node; reject it. (Overriding a PROFILE-provided stage by id is still allowed.)
        if sid in explicit_ids:
            raise RenderError(f"duplicate explicit stage id '{sid}'")
        explicit_ids.add(sid)
        resolved = dict(stage)
        # `from` supplies preset defaults; the stage's own fields override them.
        if "from" in resolved:
            preset = _load_agent_preset(resolved["from"])
            merged = _deep_merge(preset, {k: v for k, v in resolved.items() if k != "from"})
            resolved = merged
            resolved["id"] = sid
        if sid in base:
            base[sid] = _deep_merge(base[sid], resolved)
        else:
            base[sid] = resolved
            order.append(sid)
    return [base[sid] for sid in order if base[sid].get("enabled", True)]


# -------------------------------------------------------------------- model resolve


def _lookup(binding: dict[str, Any] | None, tier: str) -> str | None:
    if not binding:
        return None
    tiers = binding.get("tiers") or {}
    return tiers.get(tier) or binding.get("default")


def resolve_model(
    cfg: dict[str, Any],
    stage: dict[str, Any],
    tier: str = "standard",
    request_override: str | None = None,
) -> str:
    """Resolve a stage's model for a tier, most-specific-first, then fail loud."""
    provider = stage.get("provider") or (cfg.get("defaults", {}) or {}).get("provider")
    if not provider:
        raise RenderError(
            f"stage '{stage.get('id')}' has no provider and defaults.provider is unset"
        )
    value = (
        request_override
        or _lookup(stage.get("model"), tier)
        or _lookup((cfg.get("defaults", {}).get("models", {}) or {}).get(provider), tier)
    )
    if not value:
        raise RenderError(
            f"no model resolves for stage '{stage.get('id')}' (provider '{provider}', tier "
            f"'{tier}'): set stages[].model or defaults.models.{provider}.default"
        )
    aliases = (cfg.get("models", {}) or {}).get("aliases", {}) or {}
    if value in aliases:
        mapped = aliases[value].get(provider)
        if not mapped:
            raise RenderError(
                f"alias '{value}' has no mapping for provider '{provider}' "
                f"(stage '{stage.get('id')}')"
            )
        return mapped
    return value


def _stage_backend(stage: dict[str, Any]) -> str:
    return ((stage.get("backend") or {}).get("name")) or "generic"


# ----------------------------------------------------------------------- rendering


def _build_steps(cfg: dict[str, Any]) -> str:
    """Render the repo's build.commands into a shell block for the Validate job.

    Runs whichever of install/lint/typecheck/test are set, in that order — the
    repo's own definition of "green", not the toolkit's schema validator.
    """
    build = cfg.get("build", {}) or {}
    preset = build.get("preset", "custom")
    # Preset pre-fills commands; explicit non-empty build.commands override per key.
    commands = dict(PRESET_COMMANDS.get(preset, {}))
    for k, v in (build.get("commands", {}) or {}).items():
        if (v or "").strip():
            commands[k] = v
    order = ["install", "lint", "typecheck", "test"]
    lines: list[str] = ["set -euo pipefail"]
    for name in order:
        cmd = (commands.get(name) or "").strip()
        if cmd:
            lines.append(f'echo "::group::{name}"')
            # Split multiline commands so EVERY physical line is indented by the join below;
            # otherwise continuation lines land at column 0 and break the `run: |` YAML block.
            lines.extend(cmd.splitlines())
            lines.append('echo "::endgroup::"')
    if len(lines) == 1:
        lines.append('echo "No build commands configured; nothing to run."')
    return "\n          ".join(lines)


def build_context(cfg: dict[str, Any]) -> dict[str, str]:
    platform = cfg.get("platform", {}) or {}
    labels = platform.get("labels", {}) or {}
    routing = (cfg.get("routing", {}) or {}).get("fast_path", {}) or {}

    roles = platform.get("trusted_roles", ["owner", "member", "collaborator"])
    gh_roles = [GITHUB_ROLE_MAP[r] for r in roles if r in GITHUB_ROLE_MAP]

    # NAME of the real-user PAT the codex review lane posts/resolves with (never a value).
    codex_review_secret = ((platform.get("auth", {}) or {}).get("token_secret")) or "CODEX_REMEDIATION_TOKEN"

    stages = {s["id"]: s for s in expand_stages(cfg)}
    implement_stage = next((s for s in stages.values() if s.get("type") == "implement"), None)
    # Resolve the implementer model ONLY when the backend consumes one; otherwise the
    # app backend supplies it. Do NOT swallow a resolution error — fail loud.
    implementer_model = ""
    if implement_stage and _stage_backend(implement_stage) in BACKENDS_NEEDING_MODEL:
        implementer_model = resolve_model(cfg, implement_stage, "standard")

    return {
        "default_branch": platform.get("default_branch", "main"),
        "human_merge_label": labels.get("human_merge", "human-merge"),
        "dispatch_label": labels.get("dispatch", "agentic-task"),
        "trusted_roles_json": json.dumps(gh_roles),
        # Serialize glob lists as JSON so patterns with spaces/quotes survive intact
        # (the template parses them with jq, not word-splitting).
        "fast_path_globs_json": json.dumps(routing.get("globs", ["**/*.md"])),
        "fast_path_exclude_json": json.dumps(routing.get("exclude", [])),
        "fast_path_max_files": str(routing.get("max_files", 20)),
        "fast_path_max_lines": str(routing.get("max_lines", 200)),
        "implementer_model": implementer_model,
        "build_steps": _build_steps(cfg),
        "review_status_context": "Publish fast review result",
        "codex_review_secret": codex_review_secret,
    }


_TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def render_template(text: str, context: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in context:
            raise RenderError(f"template references unknown token '{{{{ {key} }}}}'")
        return context[key]

    return _TOKEN.sub(sub, text)


# The always-emitted core: the repo's "green" check, the review router that classifies each
# change, and the manual implementer entry point.
CORE_TEMPLATES = ["validate.yml.tmpl", "review-router.yml.tmpl", "implementor.yml.tmpl"]
# The codex review lane: request a re-review of each pushed head, and auto-resolve outdated
# Codex threads. Emitted only when a codex-backed review/security stage is configured.
REVIEW_TEMPLATES = ["request-review.yml.tmpl", "resolve-threads.yml.tmpl"]


def select_templates(stages: list[dict[str, Any]]) -> list[str]:
    """Choose which workflow templates to emit for this config.

    Module-aware, not glob-all: a config with no codex review stage does not get the review
    lane. (The `modules.auto_merge` gate template is intentionally not emitted yet — its
    trust model is under review; see PR #2 — so an auto_merge config still renders its core
    pipeline without a half-decided security gate.)
    """
    names = list(CORE_TEMPLATES)
    if any(s.get("type") in {"review", "security"} and _stage_backend(s) == "codex" for s in stages):
        names += REVIEW_TEMPLATES
    return names


def render_all(cfg: dict[str, Any], platform: str = "github") -> dict[str, str]:
    tpl_dir = TEMPLATE_ROOT / platform
    if not tpl_dir.is_dir():
        raise RenderError(f"no templates for platform '{platform}' ({tpl_dir})")
    context = build_context(cfg)
    selected = select_templates(list(expand_stages(cfg)))
    out: dict[str, str] = {}
    for name in selected:
        tpl = tpl_dir / name
        if not tpl.is_file():
            raise RenderError(f"selected template '{name}' not found in {tpl_dir}")
        out[name[: -len(".tmpl")]] = render_template(tpl.read_text(), context)
    if not out:
        raise RenderError(f"no templates selected for platform '{platform}'")
    return out


# ----------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render the agentic-foundation pipeline.")
    ap.add_argument("--config", default=".agentic/config.yml", type=Path)
    ap.add_argument("--out", type=Path, help="output dir (e.g. .github/workflows)")
    ap.add_argument("--print", action="store_true", help="print to stdout, write nothing")
    ap.add_argument("--platform", default=None, help="override platform.type")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
        validate_config(cfg)
        platform = args.platform or (cfg.get("platform", {}) or {}).get("type", "github")
        rendered = render_all(cfg, platform)
    except RenderError as exc:
        print(f"render error: {exc}", file=sys.stderr)
        return 1

    if args.print or not args.out:
        for name, content in rendered.items():
            print(f"# ===== {name} =====")
            print(content)
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (args.out / name).write_text(content)
        print(f"wrote {args.out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
