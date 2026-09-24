#!/usr/bin/env python3
"""stagr — GitHub pipeline renderer (M2).

Reads a repository's `.agentic/config.yml`, resolves it against the contract
(`stagr/config.schema.json`), and renders the platform pipeline from the
tokenized templates in `stagr/templates/workflows/<platform>/` into `.github/workflows/`.

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
    python -m stagr.render --config .agentic/config.yml --out .github/workflows
    python -m stagr.render --config .agentic/config.yml --print
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

# Toolkit data (schema + templates) ships INSIDE this package, so it is found the same
# way in a source checkout and in an installed wheel — no repo layout is assumed.
PKG_ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = PKG_ROOT / "config.schema.json"
TEMPLATE_ROOT = PKG_ROOT / "templates" / "workflows"
AGENTS_DIR = PKG_ROOT / "templates" / "agents"

# Default NAME of the real-user PAT the review lane pushes/posts with when `platform.auth.token_secret`
# is not set. Provider-neutral (the toolkit is provider-agnostic); the value lives in CI secrets.
DEFAULT_TOKEN_SECRET = "REMEDIATION_TOKEN"

GITHUB_ROLE_MAP = {
    "owner": "OWNER",
    "member": "MEMBER",
    "collaborator": "COLLABORATOR",
    "contributor": "CONTRIBUTOR",
}

# Backend names, referenced in routing/model logic across modules — kept as named constants so the
# strings are not repeated as literals in comparisons.
BACKEND_GENERIC = "generic"          # the built-in, provider-agnostic runner (the default)
BACKEND_CLAUDE_ACTION = "claude-code-action"
BACKEND_CODEX = "codex"

# Backends that consume a resolved model from the contract. App backends (codex,
# openhands, swe-agent, pr-agent) choose their own model, so resolution is skipped.
BACKENDS_NEEDING_MODEL = {BACKEND_GENERIC, BACKEND_CLAUDE_ACTION}

# Gate strengths a stage can carry.
GATE_ADVISORY = "advisory"
GATE_BLOCKING = "blocking"

# Stage types whose Codex stage drives the on-push review lane (request-review + resolve-threads).
REVIEW_LANE_TYPES = {"review", "security"}

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
        {"id": "implement", "type": "implement", "gate": GATE_ADVISORY},
        {"id": "review", "type": "review", "gate": GATE_ADVISORY},
    ],
    "standard": [
        {"id": "implement", "type": "implement"},
        {"id": "review", "type": "review", "gate": GATE_BLOCKING},
        {"id": "security", "type": "security", "gate": GATE_ADVISORY},
    ],
    "full": [
        {"id": "plan", "type": "plan", "gate": GATE_ADVISORY},
        {"id": "implement", "type": "implement"},
        {"id": "security", "type": "security", "gate": GATE_BLOCKING},
        {"id": "test", "type": "test", "gate": GATE_BLOCKING},
        {"id": "integration-test", "type": "integration-test", "gate": GATE_BLOCKING},
        {"id": "review", "type": "review", "gate": GATE_BLOCKING},
        {"id": "docs", "type": "docs", "gate": GATE_ADVISORY},
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


# A git ref is safe to interpolate into our generated workflows as long as it cannot break out of a
# double-quoted YAML scalar or a shell double-quoted string. We therefore reject only the genuinely
# dangerous characters (quotes, backtick, $, backslash, whitespace, control chars, leading '-') and
# allow every other git-valid name (e.g. `release+hotfix`, `release,2026`, `feat/x`) rather than an
# over-strict allowlist. A name with a rejected character fails loud at render time.
_UNSAFE_REF = re.compile(r"""[\s"'`$\\]""")


def _ref_is_safe(ref: str) -> bool:
    return bool(ref) and not ref.startswith("-") and not _UNSAFE_REF.search(ref) and all(ord(c) >= 0x20 for c in ref)
# A GitHub Actions secret name (what may follow `secrets.` in an expression).
_SECRET_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# A model id safe to embed in a GitHub expression string literal (no quotes/metacharacters).
_MODEL_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")

# Agent contract files change the behavior/security posture of later automation, so they must never
# ride the review fast path, whatever routing.fast_path.exclude is set to (root and nested).
MANDATORY_FAST_PATH_EXCLUDE = ["AGENTS.md", "CLAUDE.md", "**/AGENTS.md", "**/CLAUDE.md"]


# --------------------------------------------------------------------------- config


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


# ------------------------------------------------------------------------- stages


def _load_agent_preset(name: str) -> dict[str, Any]:
    # `from` comes from the (untrusted) config; an absolute/`..`/symlink value could escape
    # AGENTS_DIR and read a host YAML file into the rendered workflow/invocation. Resolve the
    # final path (follows symlinks) and reject anything outside the presets directory.
    resolved = (AGENTS_DIR / f"{name}.yml").resolve()
    if not resolved.is_relative_to(AGENTS_DIR.resolve()):
        raise RenderError(f"agent preset '{name}' resolves outside the presets directory")
    if not resolved.is_file():
        raise RenderError(f"agent preset '{name}' not found at {resolved}")
    return _read_yaml(resolved)


def expand_stages(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand `from` presets and merge the profile's stages with explicit stages."""
    profile = cfg.get("profile", "standard")
    if profile not in PROFILE_STAGES:
        raise RenderError(f"unknown profile: {profile}")
    stages_by_id = {stage_def["id"]: dict(stage_def) for stage_def in PROFILE_STAGES[profile]}
    order = [stage_def["id"] for stage_def in PROFILE_STAGES[profile]]
    explicit_ids: set[str] = set()
    for stage in cfg.get("stages", []) or []:
        stage_id = stage.get("id")
        if not stage_id:
            raise RenderError("every stage needs an id")
        # Two explicit stages sharing an id would silently deep-merge into a hybrid stage and drop
        # a graph node; reject it. (Overriding a PROFILE-provided stage by id is still allowed.)
        if stage_id in explicit_ids:
            raise RenderError(f"duplicate explicit stage id '{stage_id}'")
        explicit_ids.add(stage_id)
        resolved = dict(stage)
        # `from` supplies preset defaults; the stage's own fields override them.
        if "from" in resolved:
            preset = _load_agent_preset(resolved["from"])
            resolved = _deep_merge(preset, {k: v for k, v in resolved.items() if k != "from"})
            resolved["id"] = stage_id
        if stage_id in stages_by_id:
            stages_by_id[stage_id] = _deep_merge(stages_by_id[stage_id], resolved)
        else:
            stages_by_id[stage_id] = resolved
            order.append(stage_id)
    return [stages_by_id[stage_id] for stage_id in order if stages_by_id[stage_id].get("enabled", True)]


# -------------------------------------------------------------------- model resolve


def _model_for_tier(binding: dict[str, Any] | None, tier: str) -> str | None:
    """Pick a model id from a `{tiers: {...}, default: ...}` binding for `tier`, else None."""
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
        or _model_for_tier(stage.get("model"), tier)
        or _model_for_tier((cfg.get("defaults", {}).get("models", {}) or {}).get(provider), tier)
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
    return ((stage.get("backend") or {}).get("name")) or BACKEND_GENERIC


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
    for step_name, command in (build.get("commands", {}) or {}).items():
        if (command or "").strip():
            commands[step_name] = command
    order = ["install", "lint", "typecheck", "test"]
    lines: list[str] = ["set -euo pipefail"]
    for step_name in order:
        command = (commands.get(step_name) or "").strip()
        if command:
            lines.append(f'echo "::group::{step_name}"')
            # Split multiline commands so EVERY physical line is indented by the join below;
            # otherwise continuation lines land at column 0 and break the `run: |` YAML block.
            lines.extend(command.splitlines())
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

    default_branch = str(platform.get("default_branch", "main"))
    if not _ref_is_safe(default_branch):
        raise RenderError(
            f"platform.default_branch '{default_branch}' contains a character that cannot be safely "
            "templated into the workflows (quote, backtick, $, backslash, whitespace, control, or a "
            "leading '-'); rename the branch or set a safe default_branch"
        )

    # NAME of the real-user PAT the codex review lane posts/resolves with (never a value). Validate
    # it as a GitHub secret name so it cannot break out of the `secrets.<NAME>` expression it is
    # inserted into (e.g. a hyphen, punctuation, or newline).
    codex_review_secret = ((platform.get("auth", {}) or {}).get("token_secret")) or DEFAULT_TOKEN_SECRET
    if not _SECRET_NAME.match(str(codex_review_secret)):
        raise RenderError(
            f"platform.auth.token_secret '{codex_review_secret}' is not a valid GitHub secret name "
            "(letters, digits, underscore; not starting with a digit)"
        )

    stages = {stage["id"]: stage for stage in expand_stages(cfg)}
    implement_stage = next((stage for stage in stages.values() if stage.get("type") == "implement"), None)
    # Resolve the implementer model ONLY when the backend consumes one; otherwise the
    # app backend supplies it. Do NOT swallow a resolution error — fail loud.
    implementer_model = ""
    if implement_stage and _stage_backend(implement_stage) in BACKENDS_NEEDING_MODEL:
        implementer_model = resolve_model(cfg, implement_stage, "standard")
        # The model is embedded in a GitHub expression literal (`… || '<model>'`). A value with a
        # quote or expression metacharacter could break out and inject another operand (e.g. a
        # secret) into the implementer's --model. Constrain it to model-id characters, fail loud.
        if not _MODEL_SAFE.match(implementer_model):
            raise RenderError(
                f"resolved implementer model '{implementer_model}' contains characters unsafe to "
                "template into a workflow expression (allowed: letters, digits, and '._:/-')"
            )

    # Agent contract files are always excluded from the fast path (union with configured excludes,
    # de-duplicated, order preserved) so a nested AGENTS.md/CLAUDE.md can never be fast-path approved.
    fast_path_exclude = list(dict.fromkeys(MANDATORY_FAST_PATH_EXCLUDE + list(routing.get("exclude", []) or [])))

    # `fast_path.enabled: false` turns the lane OFF: with no trivial globs, no file ever classifies as
    # trivial, so the router always routes every PR (docs included) to the reviewer. This is the
    # one-line way a repo declares "every change goes through review" (e.g. a shared toolkit whose docs
    # other people rely on). Default is on.
    fast_path_enabled = routing.get("enabled", True)
    fast_path_globs = list(routing.get("globs", ["**/*.md"])) if fast_path_enabled else []

    # The on-push re-review requests are per-lane: ask Codex for a code review only when a codex
    # code-review stage runs on pushes, and for a security review only when a codex security stage
    # does. This keeps, e.g., the `minimal` profile (code review only) from firing a paid security
    # review it never configured. request-review.yml is emitted only when at least one of these is
    # present (select_templates), so at least one request line is always active.
    def _requests_push_review(stage_type: str) -> bool:
        return any(
            stage.get("type") == stage_type
            and _stage_backend(stage) == BACKEND_CODEX
            and _wants_push_review(stage)
            for stage in stages.values()
        )

    code_review_request = (
        "post_codex '@codex review'" if _requests_push_review("review")
        else "# no code-review stage configured; not requesting a Codex code review"
    )
    security_review_request = (
        "post_codex '@codex security review'" if _requests_push_review("security")
        else "# no security stage configured; not requesting a Codex security review"
    )

    return {
        "default_branch": default_branch,
        "human_merge_label": labels.get("human_merge", "human-merge"),
        "dispatch_label": labels.get("dispatch", "agentic-task"),
        "trusted_roles_json": json.dumps(gh_roles),
        # Serialize glob lists as JSON so patterns with spaces/quotes survive intact
        # (the template parses them with jq, not word-splitting).
        "fast_path_globs_json": json.dumps(fast_path_globs),
        "fast_path_exclude_json": json.dumps(fast_path_exclude),
        "fast_path_max_files": str(routing.get("max_files", 20)),
        "fast_path_max_lines": str(routing.get("max_lines", 200)),
        "implementer_model": implementer_model,
        "build_steps": _build_steps(cfg),
        "review_status_context": "Publish fast review result",
        "codex_review_secret": codex_review_secret,
        "code_review_request": code_review_request,
        "security_review_request": security_review_request,
    }


_TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def render_template(text: str, context: dict[str, str]) -> str:
    def substitute_token(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in context:
            raise RenderError(f"template references unknown token '{{{{ {token} }}}}'")
        return context[token]

    return _TOKEN.sub(substitute_token, text)


# The always-emitted core: the repo's "green" check and the review router that classifies each
# change. The implementer entry point is emitted separately, only when an implement stage exists
# (otherwise implementor.yml would carry an empty model and reference a key the graph never needs).
CORE_TEMPLATES = ["validate.yml.tmpl", "review-router.yml.tmpl"]
IMPLEMENTOR_TEMPLATE = "implementor.yml.tmpl"
# The codex review lane: request a re-review of each pushed head, and auto-resolve outdated
# Codex threads. Emitted only when a codex-backed review/security stage is configured.
REVIEW_TEMPLATES = ["request-review.yml.tmpl", "resolve-threads.yml.tmpl"]


def _wants_push_review(stage: dict[str, Any]) -> bool:
    """True if a review/security stage should run on each pushed head.

    A stage with no explicit `triggers` defaults to reviewing PR updates. A stage that lists
    triggers but omits `pr_updated` (e.g. only `manual` / `comment_command`) must NOT get the
    synchronize-triggered request workflow — otherwise paid reviews fire on events the stage
    never authorized.
    """
    trig = stage.get("triggers")
    if trig is None:
        return True
    return "pr_updated" in trig


def select_templates(stages: list[dict[str, Any]]) -> list[str]:
    """Choose which workflow templates to emit for this config.

    Module-aware, not glob-all: a config with no codex review stage does not get the review
    lane, and the lane is emitted only when a codex review/security stage actually runs on
    pushed heads (honoring its `triggers`). (The `modules.auto_merge` gate template is
    intentionally not emitted yet — its trust model is under review; see PR #2 — so an
    auto_merge config still renders its core pipeline without a half-decided security gate.)
    """
    names = list(CORE_TEMPLATES)
    # The implementer workflow is emitted only when the graph actually has an implement stage;
    # without one it would render with an empty model and a provider key the pipeline never uses.
    if any(stage.get("type") == "implement" for stage in stages):
        names.append(IMPLEMENTOR_TEMPLATE)
    if any(
        stage.get("type") in REVIEW_LANE_TYPES
        and _stage_backend(stage) == BACKEND_CODEX
        and _wants_push_review(stage)
        for stage in stages
    ):
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
    parser = argparse.ArgumentParser(description="Render the agentic-foundation pipeline.")
    parser.add_argument("--config", default=".agentic/config.yml", type=Path)
    parser.add_argument("--out", type=Path, help="output dir (e.g. .github/workflows)")
    parser.add_argument("--print", action="store_true", help="print to stdout, write nothing")
    parser.add_argument("--platform", default=None, help="override platform.type")
    args = parser.parse_args(argv)

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
