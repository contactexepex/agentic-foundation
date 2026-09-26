"""Structural validity + determinism of the rendered GitHub workflows."""
from __future__ import annotations

import re

import yaml

from .harness import REPO_ROOT, check, render

# A `uses:` value, without any trailing ` # comment`. Captures the action reference so the pinning
# check below can inspect the ref after the final `@`.
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.MULTILINE)
# A pinned third-party/repo action ref ends in `@<40-hex-sha>` (immutable), not `@<tag>`.
_SHA_PIN = re.compile(r"@[0-9a-f]{40}$")


def _rendered_workflows() -> dict[str, str]:
    """Every workflow rendered from the repo's own config UNION a `full`-profile config, so the
    pinning check covers the widest set of lanes (the dogfood config may not enable every stage)."""
    workflows: dict[str, str] = {}
    repo_cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    render.validate_config(repo_cfg)
    workflows.update(render.render_all(repo_cfg, "github"))
    full_cfg = {
        "version": 2, "profile": "full",
        "platform": {"type": "github", "default_branch": "main"},
        "defaults": {"provider": "anthropic",
                     "models": {"anthropic": {"default": "m"}, "openai": {"default": "o"}}},
    }
    render.validate_config(full_cfg)
    workflows.update(render.render_all(full_cfg, "github"))
    return workflows


def test_actions_sha_pinned() -> None:
    """Supply-chain integrity: every third-party action a rendered workflow `uses:` must be pinned
    to an immutable 40-char commit SHA, never a mutable tag/branch (docs/stagr/security-and-secrets.md).
    A local action (`./…`) or reusable-workflow path in the same repo is not a third-party supply-chain
    surface and is exempt; a `docker://` image ref is out of scope for this SHA rule."""
    workflows = _rendered_workflows()
    checked = 0
    for name, content in workflows.items():
        for ref in _USES.findall(content):
            if ref.startswith("./") or ref.startswith("docker://"):
                continue  # local action / container image — not a tag-pinnable third-party ref
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
