"""Docs URLs, onboarding profiles, and the static profile defaults for `stagr init`."""
from __future__ import annotations

from typing import Any

from ..render import (  # shared contract vocabulary
    DEFAULT_TOKEN_SECRET,
    GATE_BLOCKING,
    PROFILE_STAGES,
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
# review; `full` additionally declares the not-yet-rendered stages (plan/test/…); `custom` emits a
# skeleton the operator fills in.
_PROFILE_STAGES: dict[str, list[str]] = {
    "minimal": ["implement", "review"],
    "standard": ["implement", "review", "security"],
    "full": ["implement", "review", "security", "plan", "test", "integration-test", "docs"],
    "custom": [],
}

# Stages declared/validated but NOT yet rendered to workflows (roadmap — CHARTER §7). `full` lists
# them, commented, so the intended graph is visible without emitting anything unexpected.
_ROADMAP_STAGES = ("plan", "test", "integration-test", "docs")

# Canonical provider per roadmap stage (mirrors render.PROFILE_STAGES): plan/docs run Claude Code,
# test/integration-test run Codex. Serialized into the commented stages so uncommenting one keeps the
# provider the profile intended instead of silently inheriting defaults.provider.
_ROADMAP_STAGE_PROVIDER = {"plan": "anthropic", "docs": "anthropic", "test": "openai", "integration-test": "openai"}


def _canonical_gate(profile: str, stage_type: str) -> str | None:
    """The gate the canonical profile (render.PROFILE_STAGES) assigns a stage type, or None.

    The generated file lists its stages explicitly under `profile: custom`, so each stage's gate
    takes effect verbatim. Deriving gates from the shared profile definition — the single source of
    truth — keeps a generated `--profile <p>` config faithful to that profile's merge semantics
    rather than hardcoding a value that could silently strengthen or weaken it.
    """
    for stage in PROFILE_STAGES.get(profile, []):
        if stage.get("type") == stage_type:
            return stage.get("gate")
    return None


def _profile_security_blocking(profile: str) -> bool:
    """Whether the canonical profile makes the security stage blocking (drives the wizard default).

    `full` is blocking, `standard` advisory, `minimal`/`custom` have no security stage (False).
    """
    return _canonical_gate(profile, "security") == GATE_BLOCKING


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
        "security_blocking": _profile_security_blocking(profile),
    }
