"""Config loading and validation: resolve `extends` bases, load the contract, validate it
against the JSON Schema, and run the semantic checks the schema cannot express."""
from __future__ import annotations

import json
import warnings
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
    # V-S10 (non-empty blocking stages when auto_merge: true) is enforced inside this call.
    _ensure_auto_merge_coherent(expanded, cfg)

    # V-S11: dormant routing configuration warning — fast_path disabled but routing keys present.
    _warn_dormant_routing_config(cfg)

    # V-S12: static secret alias resolution — all BackendRenderer-declared aliases must resolve.
    # SecretAliasResolutionError is imported here (deferred) to keep stagr.core.errors out of
    # module-level imports and avoid any circular-import risk through the pipeline chain.
    from stagr.core.errors import SecretAliasResolutionError
    try:
        _validate_secret_alias_resolution(cfg)
    except SecretAliasResolutionError as exc:
        raise RenderError(str(exc)) from exc

    # Templating safety: building the context runs every safe-literal validator (rejecting a ${{ }}
    # expression / breakout char in a label, external-check name, glob, branch, secret name, or model,
    # and an invalid app_id / protected path). Run it here so `stagr validate` — the front door — catches
    # these, not only `render`. We only want the validation side effect.
    from .context import build_context

    build_context(cfg)


def _warn_dormant_routing_config(cfg: dict[str, Any]) -> None:
    """V-S11: warn when fast_path is disabled but routing keys remain configured.

    Routing keys (``globs`` / ``stages``) that survive with ``fast_path.enabled: false``
    will never be evaluated — they are dormant.  This is not a fatal error (the
    operator may be preparing config for a future enable), but it is almost always
    a copy-paste oversight and the warning surfaces it at validation time.

    The warning message contains the word "dormant" as required by the V-S11 spec.
    """
    routing_cfg: dict[str, Any] = cfg.get("routing") or {}
    fast_path_cfg: dict[str, Any] = routing_cfg.get("fast_path") or {}

    if fast_path_cfg.get("enabled", True):
        return  # fast_path is on (or absent); nothing to warn about

    has_globs = bool(fast_path_cfg.get("globs"))
    has_stages = bool(fast_path_cfg.get("stages"))

    if has_globs or has_stages:
        warnings.warn(
            "dormant route configuration — fast_path is disabled; routing keys are present "
            "but will not be evaluated",
            UserWarning,
            stacklevel=4,
        )


# Convention-based fallback mappings for V-S12 alias resolution.
# These aliases have pre-defined semantic resolutions that do not require
# an explicit entry in providers.<provider>.secrets.
_PROVIDER_API_KEY_ALIAS = "PROVIDER_API_KEY"
_TRUSTED_COMMENTER_TOKEN_ALIAS = "TRUSTED_COMMENTER_TOKEN"
_DEFAULT_TRUSTED_COMMENTER_SECRET = "REMEDIATION_TOKEN"
# Provider-to-default-api-key-secret mappings mirror stagr/core/render_loop.py.
_DEFAULT_PROVIDER_API_KEY_SECRETS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
}


def _resolve_alias_statically(
    alias: str,
    provider_name: str,
    provider_secrets: dict[str, str],
    api_key_secret: str | None,
    platform_token_secret: str | None,
) -> str | None:
    """Attempt to resolve a SecretRef alias to an env_name without network calls.

    Applies the V-S12 resolution rules (levels 1, 2a, 2b only — no step-3
    convention fallback that maps alias to itself):

    1. Explicit mapping in ``providers.<provider>.secrets``.
    2a. ``PROVIDER_API_KEY``: resolved to ``api_key_secret`` or provider default.
    2b. ``TRUSTED_COMMENTER_TOKEN``: resolved to ``platform_token_secret`` or the
        ``REMEDIATION_TOKEN`` default.

    Returns the resolved ``env_name`` string, or ``None`` when no rule applies.
    """
    # 1. Explicit mapping from the operator's provider secrets block.
    explicit_env_name: str | None = provider_secrets.get(alias)
    if explicit_env_name is not None:
        return explicit_env_name

    # 2a. Semantic convention: PROVIDER_API_KEY → api_key_secret or provider default.
    if alias == _PROVIDER_API_KEY_ALIAS:
        return api_key_secret or _DEFAULT_PROVIDER_API_KEY_SECRETS.get(provider_name)

    # 2b. Semantic convention: TRUSTED_COMMENTER_TOKEN → platform token or default.
    if alias == _TRUSTED_COMMENTER_TOKEN_ALIAS:
        return platform_token_secret or _DEFAULT_TRUSTED_COMMENTER_SECRET

    return None


def _validate_secret_alias_resolution(
    cfg: dict[str, Any],
    renderer_registry: Any = None,
) -> None:
    """V-S12: verify that every BackendRenderer-declared alias resolves to an env_name.

    For each active stage in the config, the registered BackendRenderer is invoked
    to obtain its ``ExecutionPlan``.  Each ``SecretRef.alias`` in the plan is then
    resolved using the three-level V-S12 rules (explicit mapping → PROVIDER_API_KEY
    convention → TRUSTED_COMMENTER_TOKEN convention).  If no rule resolves an alias,
    ``SecretAliasResolutionError`` is raised naming the alias and stage.

    Resolution is purely static: only the ``providers`` block of the config is
    consulted — no GitHub API call, no network access, no repository-secret lookup.

    ``renderer_registry`` is accepted as an optional override for the registry used
    to look up BackendRenderers.  When ``None`` (the default), the two built-in
    renderers (AnthropicClaudeBackendRenderer and OpenAICodexBackendRenderer) are
    registered automatically.  Pass a custom registry in tests to exercise code paths
    that the built-in renderers cannot reach (e.g. an unresolvable alias).

    Callers (``_validate_semantics``) catch ``SecretAliasResolutionError`` and
    re-raise as ``RenderError`` so the error surfaces in the standard validation
    error flow.
    """
    # Deferred imports avoid circular dependency: stagr.core.pipeline imports
    # from stagr.render.constants, which is a sibling of this module.
    from stagr.core.pipeline import normalize_config
    from stagr.core.backend_renderer_registry import BackendRendererRegistry
    from stagr.core.renderers.anthropic_claude_backend_renderer import (
        AnthropicClaudeBackendRenderer,
    )
    from stagr.core.renderers.openai_codex_backend_renderer import OpenAICodexBackendRenderer
    from stagr.core.errors import SecretAliasResolutionError as _CoreSecretError

    if renderer_registry is None:
        local_registry = BackendRendererRegistry()
        local_registry.register(AnthropicClaudeBackendRenderer())
        local_registry.register(OpenAICodexBackendRenderer())
    else:
        local_registry = renderer_registry

    normalized_stages = normalize_config(cfg)

    providers_cfg: dict[str, Any] = cfg.get("providers") or {}
    platform_auth_cfg: dict[str, Any] = (cfg.get("platform") or {}).get("auth") or {}
    platform_token_secret: str | None = platform_auth_cfg.get("token_secret")

    for stage in normalized_stages:
        if not local_registry.has(stage.provider, stage.backend):
            continue  # renderer not registered for this (provider, backend); skip

        backend_renderer = local_registry.get(stage.provider, stage.backend)
        try:
            execution_plan = backend_renderer.render(stage)
        except (ValueError, TypeError):
            # The renderer does not support this stage kind (e.g. OpenAICodexBackendRenderer
            # only renders review/security stages). Skip: unsupported stage kinds declare no
            # SecretRef aliases and therefore cannot fail V-S12.
            continue

        provider_entry: dict[str, Any] = providers_cfg.get(stage.provider) or {}
        provider_secrets: dict[str, str] = provider_entry.get("secrets") or {}
        api_key_secret: str | None = provider_entry.get("api_key_secret")

        for secret_ref in execution_plan.required_secrets:
            env_name = _resolve_alias_statically(
                secret_ref.alias,
                stage.provider,
                provider_secrets,
                api_key_secret,
                platform_token_secret,
            )
            if env_name is None:
                raise _CoreSecretError(
                    f"V-S12: stage '{stage.id}' (provider '{stage.provider}'): "
                    f"SecretRef alias '{secret_ref.alias}' has no mapping in "
                    f"providers.{stage.provider}.secrets and does not match a "
                    f"convention-based fallback (PROVIDER_API_KEY, TRUSTED_COMMENTER_TOKEN). "
                    f"Add an explicit mapping in providers.{stage.provider}.secrets or use "
                    f"a supported alias."
                )
