"""Least-privilege assertion: each rendered workflow's top-level ``permissions:`` block
equals its expected minimal set.

``structural.py`` only checks a ``permissions`` block EXISTS, and ``auto_merge.py`` has a
gate-specific P0 check for the auto-merge workflow. This module adds the general, per-workflow
equality assertion: every rendered workflow's top-level scopes must match ``EXPECTED`` exactly
(no missing scope, no excess scope, no drifted access level), and every rendered workflow must
be listed in ``EXPECTED`` so a newly added lane cannot ship without declaring its expected
permissions.

Rendering only the repo's own ``.agentic/config.yml`` would cover just the lanes that config
happens to enable — a new optional lane that renders for *other* valid configs could ship with
excess permissions (or no ``EXPECTED`` entry at all) and this test would still pass. So the
assertion runs over a small MATRIX of valid configs (``_matrix``) whose union activates every
renderable lane, and additionally checks the matrix collectively exercises every declared lane.
"""
from __future__ import annotations

from typing import Any

import yaml

from .harness import REPO_ROOT, check, render

# The least-privilege top-level ``permissions:`` block each rendered workflow is expected to
# carry. Adding a workflow lane without adding it here fails the test on purpose.
EXPECTED: dict[str, dict[str, str]] = {
    "auto-merge.yml": {
        "contents": "write",
        "pull-requests": "write",
        "checks": "read",
        "statuses": "read",
        "actions": "read",
    },
    "final-security-review.yml": {
        "contents": "read",
        "pull-requests": "read",
    },
    "implementor.yml": {
        "contents": "write",
        "pull-requests": "write",
        "id-token": "write",
    },
    "request-review.yml": {
        "contents": "read",
        "pull-requests": "read",
        "statuses": "read",
    },
    "resolve-threads.yml": {
        "contents": "read",
        "pull-requests": "read",
    },
    "review-router.yml": {
        "contents": "read",
        "pull-requests": "read",
        "statuses": "write",
    },
    "validate.yml": {
        "contents": "read",
    },
}


def _matrix() -> dict[str, dict[str, Any]]:
    """A small set of valid configs whose UNION activates every renderable lane.

    A single config only renders the lanes it enables, so testing one config can never catch a
    new lane that renders for a different config. These three between them cover all lanes:

    * the repo's own dogfood config (all lanes today);
    * ``profile: full`` (plan/implement/security/test/integration-test/review/docs) — exercises
      the implementer, codex code/security review, and resolve-threads lanes with auto_merge OFF;
    * a fully-featured auto-merge gate (codex review+security blocking, fast path off) — exercises
      the auto-merge lane, independent of the repo config, plus the codex review/threads lanes.
    """
    repo = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    full = {
        "version": 2,
        "profile": "full",
        "platform": {"type": "github", "default_branch": "main",
                     "auth": {"token_secret": "REMEDIATION_TOKEN"}},
        "defaults": {"provider": "anthropic",
                     "models": {"anthropic": {"default": "c"}, "openai": {"default": "o"}}},
    }
    auto_merge = {
        "version": 2,
        "profile": "custom",
        "platform": {"type": "github", "default_branch": "main",
                     "auth": {"token_secret": "REMEDIATION_TOKEN"}},
        "defaults": {"provider": "openai", "models": {"openai": {"default": "o"}}},
        "modules": {"auto_merge": True},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [
            {"id": "review", "type": "review", "backend": {"name": "codex"}, "gate": "blocking",
             "triggers": ["pr_opened", "pr_updated"]},
            {"id": "security", "type": "security", "backend": {"name": "codex"}, "gate": "blocking",
             "triggers": ["pr_opened", "pr_updated"]},
        ],
    }
    return {
        "repo (.agentic/config.yml)": repo,
        "profile: full": full,
        "modules.auto_merge gate": auto_merge,
    }


def test_least_privilege_permissions() -> None:
    rendered_names: set[str] = set()
    for label, cfg in _matrix().items():
        render.validate_config(cfg)
        rendered = render.render_all(cfg, "github")
        for name, content in sorted(rendered.items()):
            rendered_names.add(name)
            # Every rendered workflow must declare its expected permissions here, so a new lane
            # cannot ship without an explicit least-privilege set.
            check(name in EXPECTED, f"permissions: {name} (rendered by {label}) is listed in EXPECTED")
            if name not in EXPECTED:
                continue
            doc = yaml.safe_load(content)
            actual = doc.get("permissions")
            check(
                actual == EXPECTED[name],
                f"permissions: {name} top-level block equals least-privilege set "
                f"(expected {EXPECTED[name]}, got {actual})",
            )
    # The matrix must, between them, activate every declared lane — otherwise an EXPECTED entry
    # (or a whole lane) could rot unexercised, or the matrix could quietly stop covering one.
    check(
        rendered_names == set(EXPECTED),
        "permissions: matrix renders every declared lane "
        f"(unrendered {sorted(set(EXPECTED) - rendered_names)}, "
        f"undeclared {sorted(rendered_names - set(EXPECTED))})",
    )
