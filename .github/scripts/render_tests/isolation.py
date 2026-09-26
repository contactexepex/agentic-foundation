"""Principal-isolation tests: the untrusted implementer holds no publisher credential.

Negative proof for issue #48. The rendered implementer workflow drives the untrusted
implementation agent on a feature branch. It legitimately needs `contents: write` to open
its own branch, but it must NOT carry the remediation/push PAT that belongs to the trusted
publisher, and it must NOT perform any pull-request merge. This test asserts that boundary
directly against the rendered `implementor.yml` so a future edit that leaks the PAT into the
implement job, or wires a merge call into it, fails loud.
"""
from __future__ import annotations

from .harness import check, render

# A minimal config that renders the implementer workflow: custom profile, one anthropic
# implement stage, a resolvable model (mirrors the fixtures in behaviors.py / auto_merge.py).
_IMPL_CFG = {
    "version": 2,
    "profile": "custom",
    "platform": {"type": "github", "default_branch": "main"},
    "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "claude-sonnet-4-5"}}},
    "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}],
}


def test_implementer_principal_isolation() -> None:
    impl_wf = render.render_all(_IMPL_CFG, "github")["implementor.yml"]

    # The untrusted implementer never holds the trusted publisher's push-remediation PAT.
    check("REMEDIATION_TOKEN" not in impl_wf,
          "isolation: implementer workflow carries no REMEDIATION_TOKEN (no push-remediation PAT)")
    check("CODEX_PAT" not in impl_wf,
          "isolation: implementer workflow carries no CODEX_PAT")

    # Its only model secret is the Anthropic key (the implement stage runs Claude Code).
    check("ANTHROPIC_API_KEY" in impl_wf,
          "isolation: implementer workflow uses ANTHROPIC_API_KEY (the only model secret)")

    # It performs no PR-merge operation of any form (REST /merge, gh CLI, or the MCP call).
    for op in ("/merge", "--method PUT", "gh pr merge", "merge_pull_request"):
        check(op not in impl_wf,
              f"isolation: implementer workflow issues no merge operation ({op!r} absent)")
