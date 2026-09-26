"""Config loading and the secret-free health report shared by every stagr subcommand."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import render
from ..backends.generic.runner import DEFAULT_KEY_SECRET

# The conventional in-repo location of the contract. Used as every command's `--config` default and
# to detect when `init` wrote somewhere else, so its "next steps" hint can point at the right file.
DEFAULT_CONFIG_PATH = Path(".agentic/config.yml")


def _stage_provider(cfg: dict[str, Any], stage: dict[str, Any]) -> str | None:
    return stage.get("provider") or (cfg.get("defaults", {}) or {}).get("provider")


def _key_secret_name(cfg: dict[str, Any], provider: str) -> str:
    providers = cfg.get("providers", {}) or {}
    return (providers.get(provider, {}) or {}).get(
        "api_key_secret", DEFAULT_KEY_SECRET.get(provider, "MODEL_API_KEY")
    )


def _resolve_stage_model(cfg: dict[str, Any], stage: dict[str, Any], backend: str,
                         problems: list[str]) -> str | None:
    """The model string for a stage's report entry.

    App backends (e.g. codex) supply their own model, so report that; model-consuming backends
    resolve from the contract, recording a problem (and returning None) if nothing resolves.
    """
    if backend not in render.BACKENDS_NEEDING_MODEL:
        return f"(app-supplied by backend '{backend}')"
    try:
        return render.resolve_model(cfg, stage, "standard")
    except render.RenderError as exc:
        problems.append(f"stage '{stage.get('id')}': {exc}")
        return None


def _stage_secret_names(cfg: dict[str, Any], provider: str | None, backend: str) -> list[str]:
    """The provider API-key NAME (+ optional extra-headers NAME) a stage needs; empty if none.

    Only for backends that consume a model key. App backends drive their own model via their GitHub
    App and never read the provider key, so reporting it would tell the operator to create an unused
    credential. Never a secret value — only NAMES.
    """
    if not (provider and backend in render.BACKENDS_NEEDING_MODEL):
        return []
    names = [_key_secret_name(cfg, provider)]
    extra = ((cfg.get("providers", {}) or {}).get(provider, {}) or {}).get("extra_headers_secret")
    if extra:
        names.append(extra)
    return names


def _stage_report_entry(cfg: dict[str, Any], stage: dict[str, Any],
                        problems: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Build one stage's report entry; return it plus the secret NAMES that stage needs."""
    backend = render._stage_backend(stage)
    provider = _stage_provider(cfg, stage)
    entry: dict[str, Any] = {
        "id": stage.get("id"),
        "type": stage.get("type", "custom"),
        "backend": backend,
        "provider": provider,
        "gate": stage.get("gate"),
        "skill": stage.get("skill"),
        "model": _resolve_stage_model(cfg, stage, backend, problems),
    }
    return entry, _stage_secret_names(cfg, provider, backend)


def collect_report(cfg: dict[str, Any], platform: str) -> dict[str, Any]:
    """Resolve the config into a structured, secret-free health report.

    Returns model resolution per stage (or the reason it is app-supplied / unresolved),
    the set of secret NAMES the pipeline needs, the enabled modules, and the workflow
    files that would be rendered. Never contains a secret value.
    """
    stages = render.expand_stages(cfg)
    plat = cfg.get("platform", {}) or {}
    problems: list[str] = []
    report: dict[str, Any] = {
        "profile": cfg.get("profile", "standard"),
        "platform": platform,
        "default_branch": plat.get("default_branch", "main"),
        "trusted_roles": plat.get("trusted_roles", ["owner", "member", "collaborator"]),
        "modules": cfg.get("modules", {}) or {},
        "stages": [],
        "secret_names": [],
        "workflows": [],
        "problems": problems,
    }

    secret_names: set[str] = set()
    for stage in stages:
        entry, stage_secrets = _stage_report_entry(cfg, stage, problems)
        report["stages"].append(entry)
        secret_names.update(stage_secrets)

    # The Codex request/cleanup workflows author comments/resolutions with a real-user PAT (NAME
    # only). It is needed whenever ANY of them render — the code on-push lane, the final security lane,
    # or thread cleanup — so mirror _needs_codex_pat exactly. (Using the narrower push-review predicate
    # would omit the PAT for a pr_opened-only security graph that still renders final-security-review.yml
    # and reads the secret, giving a falsely healthy doctor report.)
    if render._needs_codex_pat(stages):
        secret_names.add(((plat.get("auth", {}) or {}).get("token_secret")) or render.DEFAULT_TOKEN_SECRET)

    report["secret_names"] = sorted(secret_names)
    try:
        report["workflows"] = sorted(render.render_all(cfg, platform).keys())
    except render.RenderError as exc:
        problems.append(f"render: {exc}")

    # Notes: advisory operator actions that are not config errors. The branch-protection
    # ruleset note is always emitted because an org-level ruleset on the default branch
    # prevents direct pushes regardless of auto_merge configuration: even when auto_merge
    # renders a merge-gate workflow, the ruleset is the external guard that enforces it.
    notes: list[str] = [
        "branch-protection ruleset required: configure a GitHub branch-protection ruleset on "
        "the default branch to prevent direct pushes and enforce required checks; this is "
        "required regardless of whether modules.auto_merge is enabled "
        "(see docs/stagr/onboarding-and-config.md)."
    ]
    report["notes"] = notes
    return report


def _load_validated(config_path: Path) -> tuple[dict[str, Any], str]:
    cfg = render.load_config(render.confine_config_path(config_path))
    render.validate_config(cfg)
    platform = (cfg.get("platform", {}) or {}).get("type", "github")
    return cfg, platform
