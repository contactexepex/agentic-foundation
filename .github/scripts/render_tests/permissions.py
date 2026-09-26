"""Least-privilege assertion: each rendered workflow's top-level ``permissions:`` block
equals its expected minimal set.

``structural.py`` only checks a ``permissions`` block EXISTS, and ``auto_merge.py`` has a
gate-specific P0 check for the auto-merge workflow. This module adds the general, per-workflow
equality assertion: every rendered workflow's top-level scopes must match ``EXPECTED`` exactly
(no missing scope, no excess scope, no drifted access level), and every rendered workflow must
be listed in ``EXPECTED`` so a newly added lane cannot ship without declaring its expected
permissions.
"""
from __future__ import annotations

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


def test_least_privilege_permissions() -> None:
    cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    render.validate_config(cfg)
    rendered = render.render_all(cfg, "github")

    for name, content in sorted(rendered.items()):
        # Every rendered workflow must declare its expected permissions here, so a new lane
        # cannot ship without an explicit least-privilege set.
        check(name in EXPECTED, f"permissions: {name} is listed in EXPECTED")
        if name not in EXPECTED:
            continue
        doc = yaml.safe_load(content)
        actual = doc.get("permissions")
        check(
            actual == EXPECTED[name],
            f"permissions: {name} top-level block equals least-privilege set "
            f"(expected {EXPECTED[name]}, got {actual})",
        )
