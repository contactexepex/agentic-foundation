"""Template context: render the repo's build steps, resolve the implementer model, build the token
substitution context (with per-value provenance), and expand `{{ token }}` placeholders in a template.

Every operator-controlled string that becomes a *workflow literal* (a value templated into an `env:` /
`if:` position GitHub evaluates for `${{ }}`) is routed through a safe-literal validator in `util.py`.
`build_context` returns a `RenderContext` that carries, per value, its source and whether it is such an
operator-controlled literal — so a closure test (see render_tests) can prove, independently, that every
emitted template token is produced and every operator literal was validated. Two token sets are declared
here as the single classification source: `SAFE_LITERAL_TOKENS` (operator literals, `${{`-rejected) and
`NON_OPERATOR_TOKENS` (constants, enum-locked, or derived values that cannot carry an injection, plus
`build_steps`, which is trusted operator *shell* — permitted to use `${{` — and is covered separately by
a sentinel data-flow test rather than the safe-literal family)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from .constants import (
    BACKEND_CLAUDE_ACTION,
    DEFAULT_TOKEN_SECRET,
    GITHUB_ROLE_MAP,
    MANDATORY_FAST_PATH_EXCLUDE,
    PRESET_COMMANDS,
    PROVIDER_ANTHROPIC,
)
from .errors import RenderError
from .lanes import _requires_codex_code_review, _requires_codex_security_review
from .models import _stage_backend, resolve_model
from .stages import expand_stages
from .util import (
    _MODEL_SAFE,
    _ref_is_safe,
    _SECRET_NAME,
    assert_safe_check_name,
    assert_safe_glob,
    assert_safe_label,
)

REVIEW_STATUS_CONTEXT = "Publish fast review result"


@dataclass(frozen=True)
class RenderedValue:
    """One token substitution plus its provenance. `operator_controlled` is True for a free-form operator
    string templated as a workflow literal (validated by a safe-literal validator); False for a constant,
    an enum-/schema-locked value, a derived value, or trusted shell (build_steps)."""

    token: str
    value: str
    source: str
    operator_controlled: bool


@dataclass(frozen=True)
class RenderContext:
    """The rendered token set with provenance. `substitutions()` is the plain {token: value} mapping the
    renderer consumes; it rejects a duplicate token so two values can never collide silently."""

    values: tuple[RenderedValue, ...]

    def substitutions(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for rv in self.values:
            if rv.token in out:
                raise RenderError(f"duplicate context token '{rv.token}'")
            out[rv.token] = rv.value
        return out

    # Read-only mapping convenience so `ctx["token"]` / `"token" in ctx` work like the old dict context.
    def __getitem__(self, token: str) -> str:
        return self.substitutions()[token]

    def __contains__(self, token: object) -> bool:
        return any(rv.token == token for rv in self.values)


# Single classification source of truth (the render_tests closure asserts these against real provenance
# AND against the tokens actually emitted by the templates — an unclassified or unregistered token fails).
SAFE_LITERAL_TOKENS = frozenset({
    "default_branch",
    "human_merge_label",
    "dispatch_label",
    "fast_path_globs_json",
    "fast_path_exclude_json",
    "implementer_model",
    "codex_review_secret",
    "required_status_checks_json",
    "merge_protected_paths_json",
})
NON_OPERATOR_TOKENS = frozenset({
    "trusted_roles_json",
    "fast_path_max_files",
    "fast_path_max_lines",
    "build_steps",
    "review_status_context",
    "require_codex_code_review",
    "require_codex_security_review",
    "merge_method",
})


def _build_steps(cfg: dict[str, Any]) -> str:
    """Render the repo's build.commands into a shell block for the Validate job.

    Runs whichever of install/lint/typecheck/test are set, in that order — the repo's own definition of
    "green", not the toolkit's schema validator. build.commands are TRUSTED operator shell emitted verbatim
    into a `run: |` block (so a `${{ secrets.X }}` for an authenticated install is intentionally allowed);
    untrusted PR data never reaches here (sourced only from config/preset), which a sentinel data-flow test
    asserts.
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
            # Split multiline commands so EVERY physical line is indented by the join below; otherwise
            # continuation lines land at column 0 and break the `run: |` YAML block.
            lines.extend(command.splitlines())
            lines.append('echo "::endgroup::"')
    if len(lines) == 1:
        lines.append('echo "No build commands configured; nothing to run."')
    return "\n          ".join(lines)


def _resolve_implementer_model(cfg: dict[str, Any], implement_stage: dict[str, Any] | None) -> str:
    """Resolve the implement stage's model, or "" when there is no implement stage.

    The implementer workflow runs Claude Code, so the stage must resolve to a model-consuming tool
    (Anthropic / Claude Code). A stage that resolves to Codex or another app backend cannot implement here
    yet (roadmap): fail loud rather than emit an implementer with an empty model.
    """
    if implement_stage is None:
        return ""
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
    # The model is embedded in a GitHub expression literal (`… || '<model>'`). Constrain it to model-id
    # characters so a value cannot break out and inject another operand.
    if not _MODEL_SAFE.match(model):
        raise RenderError(
            f"resolved implementer model '{model}' contains characters unsafe to template into a "
            "workflow expression (allowed: letters, digits, and '._:/-')"
        )
    return model


def _safe_default_branch(platform: dict[str, Any]) -> str:
    """The default branch, validated so it can be safely templated into the workflows."""
    default_branch = str(platform.get("default_branch", "main"))
    if not _ref_is_safe(default_branch):
        raise RenderError(
            f"platform.default_branch '{default_branch}' contains a character that cannot be safely "
            "templated into the workflows (quote, backtick, $, backslash, whitespace, control, or a "
            "leading '-'); rename the branch or set a safe default_branch"
        )
    return default_branch


def _resolve_codex_review_secret(platform: dict[str, Any]) -> str:
    """NAME of the real-user PAT the codex review lane posts/resolves with (never a value)."""
    secret = ((platform.get("auth", {}) or {}).get("token_secret")) or DEFAULT_TOKEN_SECRET
    if not _SECRET_NAME.match(str(secret)):
        raise RenderError(
            f"platform.auth.token_secret '{secret}' is not a valid GitHub secret name "
            "(letters, digits, underscore; not starting with a digit)"
        )
    if str(secret).upper().startswith("GITHUB_"):
        raise RenderError(
            f"platform.auth.token_secret '{secret}' uses the reserved GITHUB_ prefix; "
            "the review lane needs a real-user PAT, not the workflow's own GITHUB_TOKEN (GitHub also "
            "forbids user secrets named GITHUB_*). Use a different secret name."
        )
    return str(secret)


def _validated_required_status_checks(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """External checks the auto-merge gate must see green: structured {name, app_id} entries.

    Producer identity is POSITIVE (exact numeric App id), never a negative "not github-actions" rule — a
    display name alone is not an identity (any App could publish a same-named check). The name is templated
    into a single-quoted JSON env value, so reject anything that could break out of it or inject a `${{`.
    """
    raw = (cfg.get("merge", {}) or {}).get("required_status_checks", []) or []
    checks: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise RenderError(
                "merge.required_status_checks entries must be {name, app_id} objects "
                f"(got {entry!r}); a bare name cannot authenticate the producing App."
            )
        name = str(entry.get("name", ""))
        assert_safe_check_name(name, "merge.required_status_checks[].name")
        app_id = entry.get("app_id")
        if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id < 1:
            raise RenderError(
                f"merge.required_status_checks entry for '{name}' needs an integer app_id >= 1 (the "
                "immutable numeric GitHub App id of the tool that publishes the check); got "
                f"{app_id!r}. Slugs are mutable, so the numeric id is required."
            )
        checks.append({"name": name, "app_id": app_id})
    return checks


def _validated_protected_paths(cfg: dict[str, Any]) -> list[str]:
    """Glob paths whose modification by a PR forces human review (the auto-merge gate skips such a PR).

    Defaults to the control-plane surface (workflows + .agentic) when unset; an explicit [] opts out. Each
    path is templated (JSON-encoded) into an env value parsed by jq, so validate it like a glob.
    """
    merge = cfg.get("merge", {}) or {}
    raw = merge.get("protected_paths")
    if raw is None:
        raw = [".github/workflows/**", ".agentic/**"]
    paths = [str(p) for p in raw]
    for path in paths:
        assert_safe_glob(path, "merge.protected_paths[]")
    return paths


_MERGE_METHODS = ("squash", "merge", "rebase")


def _resolve_merge_method(cfg: dict[str, Any]) -> str:
    """The merge method the auto-merge gate uses (default squash). The target repo must have this method
    enabled, or GitHub rejects every merge call. Enum-locked, so it cannot carry an injection."""
    method = str((cfg.get("merge", {}) or {}).get("method", "squash"))
    if method not in _MERGE_METHODS:
        raise RenderError(f"merge.method '{method}' is not one of {list(_MERGE_METHODS)}")
    return method


def build_context(cfg: dict[str, Any]) -> RenderContext:
    platform = cfg.get("platform", {}) or {}
    labels = platform.get("labels", {}) or {}
    routing = (cfg.get("routing", {}) or {}).get("fast_path", {}) or {}

    roles = platform.get("trusted_roles", ["owner", "member", "collaborator"])
    gh_roles = [GITHUB_ROLE_MAP[r] for r in roles if r in GITHUB_ROLE_MAP]

    # Validate/resolve each operator literal (each fails loud on an unsafe/invalid value). Ordered so a
    # config with several problems surfaces a stable first error.
    default_branch = _safe_default_branch(platform)
    codex_review_secret = _resolve_codex_review_secret(platform)
    human_merge_label = assert_safe_label(str(labels.get("human_merge", "human-merge")),
                                          "platform.labels.human_merge")
    dispatch_label = assert_safe_label(str(labels.get("dispatch", "agentic-task")),
                                       "platform.labels.dispatch")

    stages = {stage["id"]: stage for stage in expand_stages(cfg)}
    stage_list = list(stages.values())
    implement_stage = next((s for s in stages.values() if s.get("type") == "implement"), None)
    implementer_model = _resolve_implementer_model(cfg, implement_stage)

    # Merge-gate policy (consumed only by the auto-merge lane). The gate demands a head-bound Codex code /
    # security review ONLY when the pipeline actually produces one, so a pipeline without that stage never
    # deadlocks waiting for a review that never runs.
    require_codex_code_review = _requires_codex_code_review(stage_list)
    require_codex_security_review = _requires_codex_security_review(stage_list)
    required_status_checks = _validated_required_status_checks(cfg)
    protected_paths = _validated_protected_paths(cfg)
    merge_method = _resolve_merge_method(cfg)

    # Agent contract files are always excluded from the fast path (union with configured excludes,
    # de-duplicated, order preserved) so a nested AGENTS.md/CLAUDE.md can never be fast-path approved.
    operator_excludes = [str(g) for g in (routing.get("exclude", []) or [])]
    for glob in operator_excludes:
        assert_safe_glob(glob, "routing.fast_path.exclude[]")
    fast_path_exclude = list(dict.fromkeys(MANDATORY_FAST_PATH_EXCLUDE + operator_excludes))

    # `fast_path.enabled: false` turns the lane OFF: with no trivial globs, no file classifies as trivial,
    # so every PR (docs included) routes to the reviewer. Default is on.
    fast_path_enabled = routing.get("enabled", True)
    operator_globs = [str(g) for g in (routing.get("globs", ["**/*.md"]) or [])]
    for glob in operator_globs:
        assert_safe_glob(glob, "routing.fast_path.globs[]")
    fast_path_globs = operator_globs if fast_path_enabled else []

    values: tuple[RenderedValue, ...] = (
        RenderedValue("default_branch", default_branch, "platform.default_branch", True),
        RenderedValue("human_merge_label", human_merge_label, "platform.labels.human_merge", True),
        RenderedValue("dispatch_label", dispatch_label, "platform.labels.dispatch", True),
        RenderedValue("codex_review_secret", codex_review_secret, "platform.auth.token_secret", True),
        RenderedValue("implementer_model", implementer_model, "<implement stage model>", True),
        # JSON lists of operator globs / check names — each element validated above / in the resolver.
        RenderedValue("fast_path_globs_json", json.dumps(fast_path_globs), "routing.fast_path.globs", True),
        RenderedValue("fast_path_exclude_json", json.dumps(fast_path_exclude), "routing.fast_path.exclude", True),
        RenderedValue("required_status_checks_json", json.dumps(required_status_checks),
                      "merge.required_status_checks", True),
        RenderedValue("merge_protected_paths_json", json.dumps(protected_paths), "merge.protected_paths", True),
        # Non-operator: constants, enum-/schema-locked, derived, or trusted shell.
        RenderedValue("trusted_roles_json", json.dumps(gh_roles), "platform.trusted_roles (enum-mapped)", False),
        RenderedValue("fast_path_max_files", str(routing.get("max_files", 20)), "routing.fast_path.max_files", False),
        RenderedValue("fast_path_max_lines", str(routing.get("max_lines", 200)), "routing.fast_path.max_lines", False),
        RenderedValue("build_steps", _build_steps(cfg), "build.commands (trusted shell)", False),
        RenderedValue("review_status_context", REVIEW_STATUS_CONTEXT, "<constant>", False),
        RenderedValue("require_codex_code_review", "true" if require_codex_code_review else "false", "<derived>", False),
        RenderedValue("require_codex_security_review", "true" if require_codex_security_review else "false", "<derived>", False),
        RenderedValue("merge_method", merge_method, "merge.method (enum)", False),
    )
    return RenderContext(values=values)


_TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def render_template(text: str, context: dict[str, str]) -> str:
    """Substitute `{{ token }}` placeholders. `context` is the plain mapping from
    `RenderContext.substitutions()`."""

    def substitute_token(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in context:
            raise RenderError(f"template references unknown token '{{{{ {token} }}}}'")
        return context[token]

    return _TOKEN.sub(substitute_token, text)


def emitted_tokens(text: str) -> set[str]:
    """The set of `{{ token }}` names a template emits — used by the closure test to prove, independently
    of the context code, that every emitted token is produced and classified."""
    return {m.group(1) for m in _TOKEN.finditer(text)}
