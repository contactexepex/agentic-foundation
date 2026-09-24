#!/usr/bin/env python3
"""Config scaffolding for `stagr init` — generate a commented `.agentic/config.yml`.

Two onboarding paths share this module:
  * a template generated non-interactively from a profile (`stagr init --profile standard`), and
  * an interactive wizard (`stagr init`) that collects a few choices, then renders the same template.

The output is YAML *with comments* (each section says what it is, its default, and how it is used),
kept concise so the file stays mostly content. Comments are why the generator emits text directly
rather than `yaml.dump` (which drops comments). Every generated profile validates against the schema
and renders, which the tests assert.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .render import (  # shared contract vocabulary
    DEFAULT_TOKEN_SECRET,
    GATE_ADVISORY,
    GATE_BLOCKING,
    PROFILE_STAGES,
)


def _schema_build_presets() -> tuple[str, ...]:
    """The valid `build.preset` values, read from the packaged schema (single source of truth).

    Deriving them here keeps the wizard's offered choices and validation in lockstep with the
    schema, so a mistyped preset can't produce a config that then fails `stagr doctor`.
    """
    schema = json.loads((Path(__file__).resolve().parent / "config.schema.json").read_text())
    return tuple(schema["properties"]["build"]["properties"]["preset"]["enum"])


BUILD_PRESETS = _schema_build_presets()
_BUILD_PRESET_OPTIONS = " | ".join(BUILD_PRESETS)

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
    """The choices a non-interactive `--profile` generation uses (the wizard overrides these)."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile '{profile}'; choose one of: {', '.join(PROFILES)}")
    return {
        "profile": profile,
        "platform": DEFAULT_PLATFORM,
        "default_branch": DEFAULT_BRANCH,
        "model": DEFAULT_MODEL,
        "token_secret": DEFAULT_TOKEN_SECRET,
        "build_preset": "custom",
        "build_test": "",
        "security_blocking": _profile_security_blocking(profile),
    }


# --------------------------------------------------------------------------- stage snippets

_IMPLEMENT_SNIPPET = """\
  # Implementer — Claude addresses review findings (manual/dispatch entry point).
  - id: implement
    type: implement
    provider: claude
    backend: { name: claude-code-action }
    triggers: [manual]"""

def _review_snippet(gate: str) -> str:
    note = ("blocks the PR until its findings are resolved" if gate == GATE_BLOCKING
            else "advisory: reports, does not block")
    return (
        f"  # Reviewer — Codex code review ({note}).\n"
        "  - id: review\n"
        "    type: review\n"
        "    provider: openai\n"
        "    skill: code-review          # built-in; override with your own via the `skills:` registry\n"
        "    backend: { name: codex }\n"
        f"    gate: {gate}\n"
        "    triggers: [pr_opened, pr_updated]"
    )

# A `custom` profile has no stages yet — define your own. Left fully commented so the file is valid
# as-is; uncomment and edit. Each stage is one agent step; `type` drives sensible defaults.
_CUSTOM_SKELETON = """\
# Define your pipeline here (this block is commented so the config is valid until you fill it in).
# Stage types: plan | implement | review | security | test | integration-test | docs | release | custom
# Example — Claude implementer + Codex code review:
# stages:
#   - id: implement
#     type: implement
#     provider: claude
#     backend: { name: claude-code-action }
#     triggers: [manual]
#   - id: review
#     type: review
#     provider: openai
#     skill: code-review
#     backend: { name: codex }
#     gate: blocking
#     triggers: [pr_opened, pr_updated]"""


def _security_snippet(blocking: bool) -> str:
    gate = GATE_BLOCKING if blocking else GATE_ADVISORY
    note = "blocks the PR" if blocking else "advisory: reports, does not block"
    return (
        f"  # Security reviewer — Codex security review ({note}).\n"
        "  - id: security\n"
        "    type: security\n"
        "    provider: openai\n"
        "    skill: security-review      # built-in; override via the `skills:` registry\n"
        "    backend: { name: codex }\n"
        f"    gate: {gate}\n"
        "    triggers: [pr_opened, pr_updated]"
    )


def _stages_block(choices: dict[str, Any]) -> str:
    profile = choices["profile"]
    if profile == "custom":
        return _CUSTOM_SKELETON

    wanted = _PROFILE_STAGES.get(profile, [])
    parts: list[str] = ["stages:"]
    if "implement" in wanted:
        parts.append(_IMPLEMENT_SNIPPET)
    if "review" in wanted:
        parts.append(_review_snippet(_canonical_gate(profile, "review") or GATE_BLOCKING))
    if "security" in wanted:
        parts.append(_security_snippet(bool(choices.get("security_blocking"))))

    roadmap = [s for s in wanted if s in _ROADMAP_STAGES]
    if roadmap:
        commented = "\n".join(f"  # - {{ id: {s}, type: {s} }}" for s in roadmap)
        parts.append(
            "  # Declared but NOT yet rendered to workflows (multi-stage rendering is roadmap —\n"
            f"  # {_DOCS_CHARTER} §7). Uncomment to declare intent; `stagr plan` shows what renders.\n"
            + commented
        )
    return "\n".join(parts)


def generate(choices: dict[str, Any]) -> str:
    """Render a commented `.agentic/config.yml` from the collected choices."""
    profile = choices.get("profile")
    if profile not in PROFILES:
        raise ValueError(f"unknown profile '{profile}'; choose one of: {', '.join(PROFILES)}")
    c = {**default_choices(profile), **choices}

    test_cmd = c["build_test"]
    test_hint = "" if test_cmd else '            # e.g. "pytest" / "npm test" — fill in your test command'
    stages_block = _stages_block(c)
    # Emit every free-form string as a JSON scalar (a valid YAML double-quoted scalar), so a value
    # that YAML would otherwise reinterpret — a branch named `on`/`no` (bool), a name with a colon
    # or quote — round-trips as the intended string instead of failing `stagr doctor`.
    branch = json.dumps(c["default_branch"])
    token_secret = json.dumps(c["token_secret"])
    model = json.dumps(c["model"])

    return f"""\
# .agentic/config.yml — generated by `stagr init` (profile: {profile}).
# One declarative file; `stagr apply` renders it into .github/workflows/. Trim or extend freely.
# Validate and preview with `stagr doctor` then `stagr plan`.
# Full reference: {_DOCS_CONFIG}
version: 2
profile: custom                 # stages are listed explicitly below

platform:
  type: {c['platform']}                  # only 'github' renders today; other platforms are roadmap
  default_branch: {branch}
  # NAME of the real-user PAT that pushes the implementer's validated fixes / re-requests reviews,
  # kept separate from the untrusted implementer's own credentials. Value lives in CI secrets.
  auth: {{ token_secret: {token_secret} }}

defaults:
  provider: claude
  models:
    # Model the Claude implementer uses. Change to your provider's model id.
    claude: {{ default: {model} }}

build:
  # What "green" means for THIS repo — your own checks. Omit the whole block for a docs-only repo.
  preset: {c['build_preset']}                # {_BUILD_PRESET_OPTIONS}
  commands:
    test: {json.dumps(test_cmd)}{test_hint}

{stages_block}

# Optional blocks (delete any to accept its default):
#   routing.fast_path      — skip paid review for trivial docs/text changes
#   modules.auto_merge     — request the fail-closed auto-merge gate (roadmap)
#   budgets                — cap cost/tokens per run
#   skills:                — register your own review/security skills (source: path), bind via stages[].skill
# See {_DOCS_CONFIG} for the full, annotated surface.
"""


# --------------------------------------------------------------------------- interactive wizard


def _ask(inp: Callable[[str], str], out: Callable[[str], None],
         prompt: str, default: str, options: str = "") -> str:
    """Ask one question, showing options and the default; empty input accepts the default."""
    opt = f" [{options}]" if options else ""
    out(f"{prompt}{opt}")
    ans = inp(f"  > (default: {default}) ").strip()
    return ans or default


def run_wizard(inp: Callable[[str], str] = input, out: Callable[[str], None] = print) -> dict[str, Any]:
    """Collect config choices interactively, grouped and defaulted. Returns a `choices` dict.

    IO is injected so the flow is unit-testable. Every prompt offers a default (Enter accepts it),
    so a user can complete onboarding by pressing Enter throughout.
    """
    out("stagr init — let's set up .agentic/config.yml. Press Enter to accept each default.\n")

    out("── Scope ──")
    profile = _ask(inp, out, "Profile (how many stages to scaffold)", "standard",
                   "minimal | standard | full | custom")
    if profile not in PROFILES:
        out(f"  (unknown profile '{profile}', using 'standard')")
        profile = "standard"

    out("\n── Platform ──")
    # Only GitHub renders today; other platforms are roadmap, so don't offer a choice that would
    # generate a config `doctor`/`apply` can't render.
    out(f"Platform: {DEFAULT_PLATFORM} (the only rendered platform today; others are roadmap).")
    platform = DEFAULT_PLATFORM
    default_branch = _ask(inp, out, "Default branch", DEFAULT_BRANCH)

    out("\n── Model & secrets ──")
    model = _ask(inp, out, "Claude implementer model id", DEFAULT_MODEL)
    token_secret = _ask(inp, out, "Secret NAME for the remediation/publish PAT", DEFAULT_TOKEN_SECRET)

    out('\n── Build ("green" checks) ──')
    build_preset = _ask(inp, out, "Build preset", "custom", _BUILD_PRESET_OPTIONS)
    if build_preset not in BUILD_PRESETS:
        # The schema permits only the listed presets; a typo would generate a config that
        # immediately fails `stagr doctor`. Fall back to the toolchain-agnostic 'custom'.
        out(f"  (unknown preset '{build_preset}', using 'custom')")
        build_preset = "custom"
    build_test = _ask(inp, out, "Test command (blank to fill later)", "")

    security_blocking = _profile_security_blocking(profile)
    if profile in ("standard", "full"):
        out("\n── Governance ──")
        prof_default = "y" if security_blocking else "n"
        ans = _ask(inp, out, "Make the security review blocking?", prof_default, "y | n").strip().lower()
        if ans in ("y", "yes", "true"):
            security_blocking = True
        elif ans in ("n", "no", "false"):
            security_blocking = False
        else:
            # Don't let an unrecognized entry silently decide a security gate — keep the profile's
            # canonical default rather than defaulting an ambiguous answer to advisory.
            out(f"  (unrecognized '{ans}', keeping the profile default: "
                f"{'blocking' if security_blocking else 'advisory'})")

    return {
        "profile": profile,
        "platform": platform,
        "default_branch": default_branch,
        "model": model,
        "token_secret": token_secret,
        "build_preset": build_preset,
        "build_test": build_test,
        "security_blocking": security_blocking,
    }
