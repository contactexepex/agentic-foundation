"""Template context: render the repo's build steps, resolve the implementer model, build the
token substitution context, and expand `{{ token }}` placeholders in a template."""
from __future__ import annotations

import json
import re
from typing import Any

from .constants import (
    BACKEND_CLAUDE_ACTION,
    DEFAULT_TOKEN_SECRET,
    GITHUB_ROLE_MAP,
    MANDATORY_FAST_PATH_EXCLUDE,
    PRESET_COMMANDS,
    PROVIDER_ANTHROPIC,
)
from .errors import RenderError
from .models import _stage_backend, resolve_model
from .stages import expand_stages
from .util import _MODEL_SAFE, _SECRET_NAME, _ref_is_safe


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
