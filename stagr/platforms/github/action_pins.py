"""Pinned third-party GitHub Actions used by every generated workflow.

Each action is pinned to a full commit SHA, never a mutable tag, per the supply-chain rule in
AGENTS.md ("Threat model"). This module is the one place a pin is defined; update it here after
auditing the new release.
"""

# actions/create-github-app-token v1.11.1 (refs/tags/v1.11.1).
APP_TOKEN_ACTION_REF = (
    "actions/create-github-app-token@c1a285145b9d317df6ced56c09f525b5c2b6f755"
    "  # v1.11.1"
)
