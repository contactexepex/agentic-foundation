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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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

# Provider ids. Provider is the primary knob: a stage declares which vendor runs it, and the
# toolkit renders OpenAI via Codex and Anthropic via Claude Code today. The executor/tool below is
# derived from the provider unless a stage pins `backend` explicitly.
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
# The Anthropic provider id was previously `claude`; rejected with a migration error (see
# _validate_semantics) so an upgraded config fails loud instead of resolving the wrong key secret.
RENAMED_ANTHROPIC_PROVIDER = "claude"

# Backend (executor/tool) names, referenced in routing/model logic across modules — kept as named
# constants so the strings are not repeated as literals in comparisons.
BACKEND_GENERIC = "generic"                     # the provider-agnostic runner (roadmap adapter)
BACKEND_CLAUDE_ACTION = "claude-code-action"    # Anthropic's Claude Code
BACKEND_CODEX = "codex"                         # OpenAI's Codex

# The coding tool the toolkit renders for each provider when a stage does not pin `backend`.
PROVIDER_TOOL = {
    PROVIDER_ANTHROPIC: BACKEND_CLAUDE_ACTION,
    PROVIDER_OPENAI: BACKEND_CODEX,
}

# Backends that consume a resolved model from the contract. App backends (codex, openhands,
# swe-agent, pr-agent) choose their own model, so resolution is skipped.
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

# Profile stages carry a provider so a profile renders correctly out of the box: implement/plan/docs
# run Claude Code (anthropic), review/security/test run Codex (openai). Without it, an unprovidered
# review stage would inherit `defaults.provider` and silently render no Codex lane.
PROFILE_STAGES: dict[str, list[dict[str, Any]]] = {
    "minimal": [
        {"id": "implement", "type": "implement", "provider": PROVIDER_ANTHROPIC, "gate": GATE_ADVISORY},
        {"id": "review", "type": "review", "provider": PROVIDER_OPENAI, "gate": GATE_ADVISORY},
    ],
    "standard": [
        {"id": "implement", "type": "implement", "provider": PROVIDER_ANTHROPIC},
        {"id": "review", "type": "review", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "security", "type": "security", "provider": PROVIDER_OPENAI, "gate": GATE_ADVISORY},
    ],
    "full": [
        {"id": "plan", "type": "plan", "provider": PROVIDER_ANTHROPIC, "gate": GATE_ADVISORY},
        {"id": "implement", "type": "implement", "provider": PROVIDER_ANTHROPIC},
        {"id": "security", "type": "security", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "test", "type": "test", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "integration-test", "type": "integration-test", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "review", "type": "review", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "docs", "type": "docs", "provider": PROVIDER_ANTHROPIC, "gate": GATE_ADVISORY},
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
    _ensure_supported_review_graph(expand_stages(cfg))


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
    expanded = [stages_by_id[stage_id] for stage_id in order if stages_by_id[stage_id].get("enabled", True)]
    _apply_backend_defaults(cfg, expanded)
    return expanded


def _apply_backend_defaults(cfg: dict[str, Any], stages: list[dict[str, Any]]) -> None:
    """Fill each stage's effective backend/tool from its provider when it does not pin one.

    Provider is the primary knob: a stage that names `provider` (or inherits `defaults.provider`)
    gets the tool the toolkit renders for that provider (anthropic -> Claude Code, openai -> Codex).
    An explicit `stages[].backend` wins (override / custom adapter). A stage whose provider has no
    known tool is left without one (`_stage_backend` -> the generic runner), so an unsupported or
    roadmap provider never silently masquerades as a supported tool.
    """
    default_provider = (cfg.get("defaults", {}) or {}).get("provider")
    for stage in stages:
        if (stage.get("backend") or {}).get("name"):
            continue
        tool = PROVIDER_TOOL.get(stage.get("provider") or default_provider)
        if tool:
            stage["backend"] = {"name": tool}


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


def _resolve_implementer_model(cfg: dict[str, Any], implement_stage: dict[str, Any] | None) -> str:
    """Resolve the implement stage's model, or "" when there is no implement stage.

    The implementer workflow runs Claude Code, so the stage must resolve to a model-consuming tool
    (Anthropic / Claude Code, or the generic runner). A stage that resolves to Codex or another app
    backend cannot implement here yet (roadmap): fail loud rather than emit an implementer with an
    empty model. A resolution failure is not swallowed either.
    """
    if implement_stage is None:
        return ""
    # The implementer workflow is hardcoded to Claude Code (reads ANTHROPIC_API_KEY, runs the resolved
    # model as a Claude model), so BOTH the provider and the tool must be Anthropic/Claude Code.
    # Checking the tool alone is not enough: `provider: openai` with an explicit
    # `backend: claude-code-action` would otherwise render the Claude workflow with an OpenAI model id.
    provider = implement_stage.get("provider") or (cfg.get("defaults", {}) or {}).get("provider")
    tool = _stage_backend(implement_stage)
    if provider != PROVIDER_ANTHROPIC or tool != BACKEND_CLAUDE_ACTION:
        raise RenderError(
            f"implement stage '{implement_stage.get('id')}' must be provider '{PROVIDER_ANTHROPIC}' "
            f"(Claude Code), which reads ANTHROPIC_API_KEY; got provider '{provider}', tool '{tool}'. "
            f"stagr renders no other implementer yet. Use provider '{PROVIDER_ANTHROPIC}', or disable "
            "the stage."
        )
    model = resolve_model(cfg, implement_stage, "standard")
    # The model is embedded in a GitHub expression literal (`… || '<model>'`). A value with a quote
    # or expression metacharacter could break out and inject another operand (e.g. a secret) into the
    # implementer's --model. Constrain it to model-id characters, fail loud.
    if not _MODEL_SAFE.match(model):
        raise RenderError(
            f"resolved implementer model '{model}' contains characters unsafe to template into a "
            "workflow expression (allowed: letters, digits, and '._:/-')"
        )
    return model


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
    # The review lane must post as a REAL-USER PAT; GITHUB_TOKEN is the workflow's own principal
    # (read-scoped in these workflows), so a review request posted with it is skipped or fails. Any
    # GITHUB_-prefixed name is also a reserved secret name GitHub forbids. Reject it so `doctor`
    # cannot call a pipeline healthy while conflating the workflow token with the required PAT.
    if str(codex_review_secret).upper().startswith("GITHUB_"):
        raise RenderError(
            f"platform.auth.token_secret '{codex_review_secret}' uses the reserved GITHUB_ prefix; "
            "the review lane needs a real-user PAT, not the workflow's own GITHUB_TOKEN (GitHub also "
            "forbids user secrets named GITHUB_*). Use a different secret name."
        )

    stages = {stage["id"]: stage for stage in expand_stages(cfg)}
    implement_stage = next((stage for stage in stages.values() if stage.get("type") == "implement"), None)
    implementer_model = _resolve_implementer_model(cfg, implement_stage)

    # Agent contract files are always excluded from the fast path (union with configured excludes,
    # de-duplicated, order preserved) so a nested AGENTS.md/CLAUDE.md can never be fast-path approved.
    fast_path_exclude = list(dict.fromkeys(MANDATORY_FAST_PATH_EXCLUDE + list(routing.get("exclude", []) or [])))

    # `fast_path.enabled: false` turns the lane OFF: with no trivial globs, no file ever classifies as
    # trivial, so the router always routes every PR (docs included) to the reviewer. This is the
    # one-line way a repo declares "every change goes through review" (e.g. a shared toolkit whose docs
    # other people rely on). Default is on.
    fast_path_enabled = routing.get("enabled", True)
    fast_path_globs = list(routing.get("globs", ["**/*.md"])) if fast_path_enabled else []

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
# The codex code-review lane: re-request a code review of each pushed head, so review iterates as the
# PR is updated. Emitted when a codex-backed review stage runs on pushed heads.
CODE_REVIEW_TEMPLATE = "request-review.yml.tmpl"
# The codex security-review lane: request ONE security review as the final pre-merge step, once the
# code review has converged — never concurrent with the code review (Codex errors on a concurrent
# pair). Emitted when a codex-backed security stage runs on pushed heads.
SECURITY_REVIEW_TEMPLATE = "final-security-review.yml.tmpl"
# Auto-resolve outdated Codex threads. Emitted whenever any codex review/security lane runs.
RESOLVE_THREADS_TEMPLATE = "resolve-threads.yml.tmpl"


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


def _has_implement_stage(stages: list[dict[str, Any]]) -> bool:
    # The implementer workflow is emitted only when the graph actually has an implement stage;
    # without one it would render with an empty model and a provider key the pipeline never uses.
    return any(stage.get("type") == "implement" for stage in stages)


def _has_codex_stage_of(stages: list[dict[str, Any]], stage_type: str) -> bool:
    return any(
        stage.get("type") == stage_type
        and _stage_backend(stage) == BACKEND_CODEX
        and _wants_push_review(stage)
        for stage in stages
    )


def _has_codex_code_review(stages: list[dict[str, Any]]) -> bool:
    # request-review.yml renders when a codex CODE review stage runs on pushed heads.
    return _has_codex_stage_of(stages, "review")


def _has_codex_security_review(stages: list[dict[str, Any]]) -> bool:
    # final-security-review.yml renders when a codex SECURITY stage runs on pushed heads.
    return _has_codex_stage_of(stages, "security")


def _has_codex_push_review(stages: list[dict[str, Any]]) -> bool:
    # resolve-threads.yml renders whenever any codex review/security lane runs.
    return _has_codex_code_review(stages) or _has_codex_security_review(stages)


def _ensure_supported_review_graph(stages: list[dict[str, Any]]) -> None:
    """Reject a graph whose Codex security lane could never fire.

    The final security review runs ONLY after the Codex code review converges
    (final-security-review.yml waits for the code review's "Completed" row before requesting it). A
    graph with a Codex `security` stage but no Codex `review` stage would therefore render a security
    workflow that no event can ever satisfy, silently disabling the configured stage. Fail loud at the
    front door instead, so an unsupported graph is a clear error rather than a dead lane.
    """
    if _has_codex_security_review(stages) and not _has_codex_code_review(stages):
        raise RenderError(
            "a Codex security-review stage requires a Codex code-review ('review') stage: the security "
            "review runs only after the code review has converged, so a security stage on its own would "
            "render a workflow that never fires. Add a codex-backed 'review' stage, or remove the "
            "'security' stage."
        )


@dataclass(frozen=True)
class Lane:
    """One rendered workflow lane: its `templates` are emitted when `applies` holds for the
    fully-expanded stage graph. `LANES` is the single place a lane is wired in, so a future lane
    (multi-stage gates, other platforms — CHARTER §7) is one entry here, not another branch.
    """

    name: str
    applies: Callable[[list[dict[str, Any]]], bool]
    templates: tuple[str, ...]


# The lane registry, in emit order. `core` (the repo's "green" check + review router) always
# applies; each other lane is module-aware and renders only when a matching stage exists. (The
# `modules.auto_merge` gate is intentionally not a lane yet — its trust model is under review; see
# PR #2 — so an auto_merge config still renders its core pipeline.)
LANES: tuple[Lane, ...] = (
    Lane("core", lambda stages: True, tuple(CORE_TEMPLATES)),
    Lane("implementor", _has_implement_stage, (IMPLEMENTOR_TEMPLATE,)),
    Lane("codex-code-review", _has_codex_code_review, (CODE_REVIEW_TEMPLATE,)),
    Lane("codex-security-review", _has_codex_security_review, (SECURITY_REVIEW_TEMPLATE,)),
    Lane("codex-threads", _has_codex_push_review, (RESOLVE_THREADS_TEMPLATE,)),
)


def select_templates(stages: list[dict[str, Any]]) -> list[str]:
    """Choose which workflow templates to emit, driven by the `LANES` registry (emit order)."""
    _ensure_supported_review_graph(stages)
    names: list[str] = []
    for lane in LANES:
        if lane.applies(stages):
            names.extend(lane.templates)
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
        out[name[: -len(".tmpl")]] = render_template(tpl.read_text(encoding="utf-8"), context)
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
        cfg = load_config(confine_config_path(args.config))
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
        (args.out / name).write_text(content, encoding="utf-8")
        print(f"wrote {args.out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
