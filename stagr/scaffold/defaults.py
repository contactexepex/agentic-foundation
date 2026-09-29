"""Docs URLs, onboarding profiles, and the static profile defaults for `stagr init`."""
from __future__ import annotations

from typing import Any

from ..render import (  # shared contract vocabulary
    DEFAULT_TOKEN_SECRET,
    GATE_BLOCKING,
)

from .detect import CUSTOM_PRESET


# Public doc links, so a generated config dropped into ANOTHER repo points at docs that exist there
# (a relative `docs/…` reference would resolve inside the consumer repo, where they do not exist).
_DOCS_BASE = "https://github.com/contactexepex/agentic-foundation/blob/main/docs"
_DOCS_CONFIG = f"{_DOCS_BASE}/CONFIGURATION.md"
_DOCS_CHARTER = f"{_DOCS_BASE}/CHARTER.md"

# The onboarding profiles `init` understands, smallest to largest. These size the generated file;
# the flow is always the recommended Claude-implementer + Codex-reviewer pair, which is what renders
# today. (`profile:` in the file is written as `custom` because the stages are listed explicitly.)
PROFILES = ("minimal", "standard", "full", "custom")

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_PLATFORM = "github"
DEFAULT_BRANCH = "main"

# Which stages each profile includes. `minimal` = implement + review; `standard` adds a security
# review; `full` additionally shows a commented `integration-test` example (a stage that cannot render
# yet); `custom` emits a skeleton the operator fills in. `plan` and `docs` are NOT dev-lane stages —
# they belong to the Planning and CD sibling toolkits (see docs/stagr/dev-lane.md), so no profile
# emits them.
_PROFILE_STAGES: dict[str, list[str]] = {
    "minimal": ["implement", "review"],
    "standard": ["implement", "review", "security"],
    "full": ["implement", "review", "security", "integration-test"],
    "custom": [],
}

# Stages declared/validated but NOT yet rendered to workflows: they need a build/test backend that
# does not exist yet. `full` lists them, commented, so the intended graph is visible without
# emitting anything `stagr plan` cannot render.
_ROADMAP_STAGES = ("integration-test",)

# The gate `init` writes for every Codex review/security stage, in every profile. Always blocking:
# the neutral pipeline (`stagr plan` / `stagr apply`) rejects an advisory Codex stage, because both
# Codex stages share one review scope (design-docs/06-runtime-boundary.md, shared-scope rule), so a
# generated config must never contain one. This mirrors the review/security gates in
# core.normalize._PROFILE_STAGE_DEFAULTS (the neutral profile definitions); a test asserts they agree.
# The legacy `python -m stagr.render` lane keeps its own render.PROFILE_STAGES, where `minimal` and
# `standard` make review/security advisory — `init` deliberately does not read it.
CODEX_STAGE_GATE = GATE_BLOCKING


def default_choices(profile: str) -> dict[str, Any]:
    """The static default choices for a profile (pure — no filesystem or network access).

    `build_preset` defaults to `CUSTOM_PRESET`; `init` autodetects the repo's toolchain and overlays
    it on top (see `detect_build_preset` / `cli._resolve_init_choices`), and the wizard overrides all
    of these interactively.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile '{profile}'; choose one of: {', '.join(PROFILES)}")
    return {
        "profile": profile,
        "platform": DEFAULT_PLATFORM,
        "default_branch": DEFAULT_BRANCH,
        "model": DEFAULT_MODEL,
        "token_secret": DEFAULT_TOKEN_SECRET,
        "build_preset": CUSTOM_PRESET,
        "build_test": "",
    }
