"""Structural validity + determinism of the rendered GitHub workflows."""
from __future__ import annotations

import re

import yaml

from .harness import REPO_ROOT, check, render

# A pinned third-party/repo action ref ends in `@<40-hex-sha>` (immutable), not `@<tag>`.
_SHA_PIN = re.compile(r"@[0-9a-f]{40}$")


def _rendered_workflows() -> dict[str, str]:
    """Every workflow rendered from the repo's own config AND a `full`-profile config, so the pinning
    check covers the widest set of lanes (the dogfood config may not enable every stage). Keys are
    namespaced per source config so a workflow that BOTH configs emit under the same filename is kept
    as two distinct entries — a plain dict merge would clobber one rendering and leave its
    config-dependent action refs unchecked."""
    configs = {
        "repo": render.load_config(REPO_ROOT / ".agentic" / "config.yml"),
        "full": {
            "version": 2, "profile": "full",
            "platform": {"type": "github", "default_branch": "main"},
            "defaults": {"provider": "anthropic",
                         "models": {"anthropic": {"default": "m"}, "openai": {"default": "o"}}},
        },
    }
    workflows: dict[str, str] = {}
    for label, cfg in configs.items():
        render.validate_config(cfg)
        for name, content in render.render_all(cfg, "github").items():
            workflows[f"{label}:{name}"] = content
    return workflows


def _iter_uses(node: object):
    """Yield every `uses:` value in a parsed workflow, wherever it appears. Walking the parsed YAML
    (not the raw text) means every valid spelling of the key — `uses:`, `- uses : x`, `"uses"`, an
    inline mapping — is caught, so a mutable action ref cannot slip past behind YAML formatting."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                yield value
            else:
                yield from _iter_uses(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_uses(item)


def test_actions_sha_pinned() -> None:
    """Supply-chain integrity: every third-party action a rendered workflow `uses:` must be pinned
    to an immutable 40-char commit SHA, never a mutable tag/branch (docs/stagr/security-and-secrets.md).
    A local action (`./…`) or reusable-workflow path in the same repo is not a third-party supply-chain
    surface and is exempt; a `docker://` image ref must be digest-pinned to an immutable `@sha256:`
    digest (a mutable tag like `:latest` is rejected)."""
    workflows = _rendered_workflows()
    checked = 0
    for name, content in workflows.items():
        for ref in _iter_uses(yaml.safe_load(content)):
            if ref.startswith("./"):
                continue  # local action / reusable workflow — not a third-party supply-chain surface
            if ref.startswith("docker://"):
                checked += 1
                check("@sha256:" in ref,
                      f"pin: {name} docker image '{ref}' is pinned to an immutable @sha256 digest (not a mutable tag)")
                continue
            checked += 1
            check(bool(_SHA_PIN.search(ref)),
                  f"pin: {name} action '{ref}' is pinned to a 40-char commit SHA (not a mutable tag)")
    check(checked >= 1, "pin: at least one third-party `uses:` action was checked")


def test_render_structural() -> None:
    cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    render.validate_config(cfg)
    rendered = render.render_all(cfg, "github")
    check(len(rendered) >= 1, "render: produced at least one workflow")
    for name, content in rendered.items():
        # no unresolved renderer tokens ({{ token }}) — GitHub's own ${{ ... }} expressions
        # are intentionally NOT matched by render._TOKEN, so they are left intact.
        check(render._TOKEN.search(content) is None, f"render: {name} has no unresolved tokens")
        # valid YAML with required top-level keys
        doc = yaml.safe_load(content)
        check(isinstance(doc, dict) and "jobs" in doc and "permissions" in doc, f"render: {name} has jobs + permissions")
        check(True if "on" in doc or True in doc else False, f"render: {name} has triggers")
        # no secret values inlined
        check(not re.search(r"sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}", content), f"render: {name} inlines no secret value")
    # deterministic
    check(render.render_all(cfg, "github") == rendered, "render: deterministic / idempotent")
