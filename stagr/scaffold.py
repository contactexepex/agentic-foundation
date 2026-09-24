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

from typing import Any, Callable

from .render import DEFAULT_TOKEN_SECRET  # single source of truth for the default PAT secret name

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
        "security_blocking": False,
    }


# --------------------------------------------------------------------------- stage snippets

_IMPLEMENT_SNIPPET = """\
  # Implementer — Claude addresses review findings (manual/dispatch entry point).
  - id: implement
    type: implement
    provider: claude
    backend: { name: claude-code-action }
    triggers: [manual]"""

_REVIEW_SNIPPET = """\
  # Reviewer — Codex code review; blocks the PR until its findings are resolved.
  - id: review
    type: review
    provider: openai
    skill: code-review          # built-in; override with your own via the `skills:` registry
    backend: { name: codex }
    gate: blocking
    triggers: [pr_opened, pr_updated]"""

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
    gate = "blocking" if blocking else "advisory"
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
        parts.append(_REVIEW_SNIPPET)
    if "security" in wanted:
        parts.append(_security_snippet(bool(choices.get("security_blocking"))))

    roadmap = [s for s in wanted if s in _ROADMAP_STAGES]
    if roadmap:
        commented = "\n".join(f"  # - {{ id: {s}, type: {s} }}" for s in roadmap)
        parts.append(
            "  # Declared but NOT yet rendered to workflows (multi-stage rendering is roadmap —\n"
            "  # docs/CHARTER.md §7). Uncomment to declare intent; `stagr plan` shows what renders.\n"
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

    return f"""\
# .agentic/config.yml — generated by `stagr init` (profile: {profile}).
# One declarative file; `stagr apply` renders it into .github/workflows/. Trim or extend freely.
# Validate and preview with `stagr doctor` then `stagr plan`. Full reference: docs/CONFIGURATION.md
version: 2
profile: custom                 # stages are listed explicitly below

platform:
  type: {c['platform']}                  # github | gitlab | azure_devops | bitbucket
  default_branch: {c['default_branch']}
  # NAME of the real-user PAT that pushes the implementer's validated fixes / re-requests reviews,
  # kept separate from the untrusted implementer's own credentials. Value lives in CI secrets.
  auth: {{ token_secret: {c['token_secret']} }}

defaults:
  provider: claude
  models:
    # Model the Claude implementer uses. Change to your provider's model id.
    claude: {{ default: {c['model']} }}

build:
  # What "green" means for THIS repo — your own checks. Omit the whole block for a docs-only repo.
  preset: {c['build_preset']}                # python | node | maven | gradle | go | rust | dotnet | custom
  commands:
    test: "{test_cmd}"{test_hint}

{stages_block}

# Optional blocks (delete any to accept its default):
#   routing.fast_path      — skip paid review for trivial docs/text changes
#   modules.auto_merge     — request the fail-closed auto-merge gate (roadmap)
#   budgets                — cap cost/tokens per run
#   skills:                — register your own review/security skills (source: path), bind via stages[].skill
# See docs/CONFIGURATION.md for the full, annotated surface.
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
    platform = _ask(inp, out, "SCM/CI platform", DEFAULT_PLATFORM,
                    "github | gitlab | azure_devops | bitbucket")
    default_branch = _ask(inp, out, "Default branch", DEFAULT_BRANCH)

    out("\n── Model & secrets ──")
    model = _ask(inp, out, "Claude implementer model id", DEFAULT_MODEL)
    token_secret = _ask(inp, out, "Secret NAME for the remediation/publish PAT", DEFAULT_TOKEN_SECRET)

    out('\n── Build ("green" checks) ──')
    build_preset = _ask(inp, out, "Build preset", "custom",
                        "python | node | maven | gradle | go | rust | dotnet | custom")
    build_test = _ask(inp, out, "Test command (blank to fill later)", "")

    security_blocking = False
    if profile in ("standard", "full"):
        out("\n── Governance ──")
        ans = _ask(inp, out, "Make the security review blocking?", "n", "y | n")
        security_blocking = ans.strip().lower() in ("y", "yes", "true")

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
