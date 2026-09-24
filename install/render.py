#!/usr/bin/env python3
"""agentic-foundation — GitHub pipeline renderer (M2).

Reads a repository's `.agentic/config.yml`, resolves it against the contract
(`install/config.schema.json`), and renders the platform pipeline from the
tokenized templates in `templates/workflows/<platform>/` into `.github/workflows/`.

Design notes
------------
- Deterministic: given the same config + templates, output is byte-identical.
- No network, no secrets. Secrets are referenced by NAME only; this renderer never
  reads or emits a secret value.
- Provider/model resolution is the reusable core (M3's doctor/plan/apply import it):
  per-stage, per-tier, precedence = per-request > stage > org/account default, with
  `models.aliases` expansion, and FAIL-LOUD if nothing resolves (no hidden default).
- The core workflows are generic; their only config-derived parts are scalars/small
  lists, so templating is simple token substitution (`{{ token }}`), not loops.

CLI:
    python install/render.py --config .agentic/config.yml --out .github/workflows
    python install/render.py --config .agentic/config.yml --print   # to stdout, no writes
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

# Normalized (platform-neutral) trusted roles -> GitHub author_association values.
GITHUB_ROLE_MAP = {
    "owner": "OWNER",
    "member": "MEMBER",
    "collaborator": "COLLABORATOR",
    "contributor": "CONTRIBUTOR",
}

# Profile -> default stage graph (expanded when the config does not list a stage of
# the same id). Kept in sync with docs/CONFIGURATION.md `profile`.
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


# --------------------------------------------------------------------------- config


def load_config(path: Path) -> dict[str, Any]:
    try:
        cfg = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise RenderError(f"config not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise RenderError(f"config is not valid YAML: {exc}") from exc
    if not isinstance(cfg, dict):
        raise RenderError("config root must be a mapping")
    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(cfg), key=lambda e: list(e.path))
    if errors:
        lines = "; ".join(
            f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors
        )
        raise RenderError(f"config does not conform to schema: {lines}")


# ------------------------------------------------------------------------- stages


def expand_stages(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge the profile's default stages with explicitly listed stages.

    A listed stage with the same id overrides the profile's; otherwise it is appended.
    """
    profile = cfg.get("profile", "standard")
    if profile not in PROFILE_STAGES:
        raise RenderError(f"unknown profile: {profile}")
    base = {s["id"]: dict(s) for s in PROFILE_STAGES[profile]}
    order = [s["id"] for s in PROFILE_STAGES[profile]]
    for stage in cfg.get("stages", []) or []:
        sid = stage.get("id")
        if not sid:
            raise RenderError("every stage needs an id")
        if sid in base:
            base[sid].update(stage)
        else:
            base[sid] = dict(stage)
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
    """Resolve a stage's model for a tier, most-specific-first, then fail loud.

    1. per-request override  2. stage model  3. defaults.models.<provider>
    A resolved value that matches a `models.aliases` name expands per provider.
    """
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
    # Alias expansion (last step): a value matching an alias name maps per provider.
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


# ----------------------------------------------------------------------- rendering


def build_context(cfg: dict[str, Any]) -> dict[str, str]:
    """Compute the token values the GitHub templates substitute."""
    platform = cfg.get("platform", {}) or {}
    labels = platform.get("labels", {}) or {}
    routing = (cfg.get("routing", {}) or {}).get("fast_path", {}) or {}

    roles = platform.get("trusted_roles", ["owner", "member", "collaborator"])
    gh_roles = [GITHUB_ROLE_MAP[r] for r in roles if r in GITHUB_ROLE_MAP]

    # Resolve the implementer model default (used by the claude implementor template).
    stages = {s["id"]: s for s in expand_stages(cfg)}
    implement_stage = next(
        (s for s in stages.values() if s.get("type") == "implement"), None
    )
    implementer_model = ""
    if implement_stage:
        try:
            implementer_model = resolve_model(cfg, implement_stage, "standard")
        except RenderError:
            implementer_model = ""  # left to the workflow's own var fallback

    globs = routing.get("globs", ["**/*.md"])
    exclude = routing.get("exclude", [])
    return {
        "default_branch": platform.get("default_branch", "main"),
        "human_merge_label": labels.get("human_merge", "human-merge"),
        "dispatch_label": labels.get("dispatch", "agentic-task"),
        "trusted_roles_json": json.dumps(gh_roles),
        "fast_path_globs": " ".join(globs),
        "fast_path_exclude": " ".join(exclude),
        "fast_path_max_files": str(routing.get("max_files", 20)),
        "fast_path_max_lines": str(routing.get("max_lines", 200)),
        "implementer_model": implementer_model,
        "review_status_context": "Publish fast review result",
        "codex_bot_login_rest": "chatgpt-codex-connector[bot]",
        "codex_bot_login_graphql": "chatgpt-codex-connector",
    }


_TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def render_template(text: str, context: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in context:
            raise RenderError(f"template references unknown token '{{{{ {key} }}}}'")
        return context[key]

    return _TOKEN.sub(sub, text)


def render_all(cfg: dict[str, Any], platform: str = "github") -> dict[str, str]:
    """Render every template for the platform. Returns {output_filename: content}."""
    tpl_dir = TEMPLATE_ROOT / platform
    if not tpl_dir.is_dir():
        raise RenderError(f"no templates for platform '{platform}' ({tpl_dir})")
    context = build_context(cfg)
    out: dict[str, str] = {}
    for tpl in sorted(tpl_dir.glob("*.yml.tmpl")):
        out[tpl.name[: -len(".tmpl")]] = render_template(tpl.read_text(), context)
    if not out:
        raise RenderError(f"no *.yml.tmpl templates found in {tpl_dir}")
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
