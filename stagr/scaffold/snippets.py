"""Config-text builders — the commented YAML stage snippets that make up the generated file."""
from __future__ import annotations

from typing import Any

from .defaults import (
    _PROFILE_STAGES,
    _ROADMAP_STAGES,
    CODEX_STAGE_GATE,
)


# --------------------------------------------------------------------------- stage snippets

_IMPLEMENT_SNIPPET = """\
  # Implementer — Claude addresses review findings (manual/dispatch entry point).
  - id: implement
    type: implement
    provider: anthropic
    triggers: [manual]"""

# The two gate categories, explained once, right above the stages they apply to.
_GATE_EXPLANATION_LINES = (
    "Every stage has one gate: `blocking` or `advisory`.",
    "  advisory - posts comments; never stops the pull request from merging.",
    "  blocking - the stage must complete, and all of its review comments/threads must be",
    "             resolved, before the pull request can merge.",
    "The Codex review and security stages below must be blocking: `stagr plan` rejects advisory ones.",
)

# Stages that cannot be rendered yet, shown commented so the intended baseline is visible. Each entry
# is the YAML of one stage. They stay commented: until a build/test backend exists, an active copy
# renders only a placeholder workflow that builds and tests nothing (`stagr plan` warns).
_UNAVAILABLE_BASELINE_STAGE_LINES = (
    "NOT AVAILABLE YET - these need a build/test backend that does not exist yet. They will become",
    "the default blocking stages, so the standard baseline is: build compiles + unit tests green +",
    "code review complete + security review complete. Until then they would render only a placeholder",
    "workflow that builds and tests nothing (`stagr plan` warns), so keep them commented.",
    "- id: build",
    "  type: custom",
    "  gate: blocking",
    "- id: test",
    "  type: test",
    "  gate: blocking",
)

_OPTIONAL_STAGE_LINES = (
    "Optional stages: add the extra checks your team wants (integration tests, performance tests, SQL",
    "validation, SAST/DAST, ...) as more stages, and give each a gate: `blocking` if it must pass",
    "before merge, `advisory` if it should only comment. They also need the build/test backend.",
)

_ROADMAP_STAGE_LINES = {
    "integration-test": ("- id: integration-test", "  type: integration-test", "  gate: blocking"),
}

_STAGES_LIST_COMMENT_PREFIX = "  # "
_CUSTOM_SKELETON_COMMENT_PREFIX = "#   "


def _review_snippet() -> str:
    return (
        "  # Reviewer — Codex code review (blocking: must complete, and every review comment resolved).\n"
        "  - id: review\n"
        "    type: review\n"
        "    provider: openai            # OpenAI/Codex is the rendered reviewer (tool derived from provider)\n"
        "    skill: code-review          # built-in; override with your own via the `skills:` registry\n"
        f"    gate: {CODEX_STAGE_GATE}\n"
        # On PR open the Codex app reviews natively (that is what services `pr_opened`); stagr's
        # rendered workflow re-requests a review on each push (`pr_updated`), which Codex does not
        # auto-handle.
        "    triggers: [pr_opened, pr_updated]   # pr_opened: Codex app reviews on open; "
        "pr_updated: stagr re-requests per push"
    )


def _security_snippet() -> str:
    return (
        "  # Security reviewer — Codex security review (blocking: must complete, and every comment resolved).\n"
        "  - id: security\n"
        "    type: security\n"
        "    provider: openai            # OpenAI/Codex is the rendered reviewer (tool derived from provider)\n"
        "    skill: security-review      # built-in; override via the `skills:` registry\n"
        f"    gate: {CODEX_STAGE_GATE}\n"
        # UNLIKE the code review, the security review runs ONCE as the final pre-merge step
        # (final-security-review.yml), after the code review converges — never on open and never per
        # push — so it never races the code review (Codex's backend errors on a concurrent pair). These
        # triggers only select the security lane; configure the Codex App to auto-run the CODE review
        # only on open (a ChatGPT-side setting the toolkit cannot render), or its native security review
        # will race the code review on every open.
        "    triggers: [pr_opened, pr_updated]   # selects the security lane; the review itself runs "
        "once, after the code review (final-security-review.yml)"
    )


def _commented(lines: tuple[str, ...], comment_prefix: str) -> str:
    return "\n".join(f"{comment_prefix}{line}".rstrip() for line in lines)


def _unavailable_and_optional_stage_notes(comment_prefix: str, roadmap_stage_ids: tuple[str, ...]) -> str:
    """The commented, not-yet-renderable stage examples plus the note on adding optional stages."""
    sections = [_commented(_UNAVAILABLE_BASELINE_STAGE_LINES, comment_prefix)]
    for stage_id in roadmap_stage_ids:
        sections.append(_commented(_ROADMAP_STAGE_LINES[stage_id], comment_prefix))
    sections.append(_commented(_OPTIONAL_STAGE_LINES, comment_prefix))
    return "\n".join(sections)


# A `custom` profile has no stages yet — define your own. Left fully commented so the file is valid
# as-is; uncomment and edit. Each stage is one agent step; `type` drives sensible defaults.
_CUSTOM_SKELETON = (
    "# Define your pipeline here (this block is commented so the config is valid until you fill it in).\n"
    "# Stage types: plan | implement | review | security | test | integration-test | docs | release | custom\n"
    + _commented(_GATE_EXPLANATION_LINES, "# ")
    + "\n# Example — Claude implementer + Codex code review (the tool is derived from `provider`):\n"
    "# stages:\n"
    "#   - id: implement\n"
    "#     type: implement\n"
    "#     provider: anthropic\n"
    "#     triggers: [manual]\n"
    "#   - id: review\n"
    "#     type: review\n"
    "#     provider: openai\n"
    "#     skill: code-review\n"
    f"#     gate: {CODEX_STAGE_GATE}\n"
    "#     triggers: [pr_opened, pr_updated]\n"
    + _unavailable_and_optional_stage_notes(_CUSTOM_SKELETON_COMMENT_PREFIX, ())
)


def _stages_block(choices: dict[str, Any]) -> str:
    profile = choices["profile"]
    if profile == "custom":
        return _CUSTOM_SKELETON

    wanted = _PROFILE_STAGES.get(profile, [])
    parts: list[str] = [_commented(_GATE_EXPLANATION_LINES, "# "), "stages:"]
    if "implement" in wanted:
        parts.append(_IMPLEMENT_SNIPPET)
    if "review" in wanted:
        parts.append(_review_snippet())
    if "security" in wanted:
        parts.append(_security_snippet())

    roadmap_stage_ids = tuple(stage_id for stage_id in wanted if stage_id in _ROADMAP_STAGES)
    parts.append(_unavailable_and_optional_stage_notes(_STAGES_LIST_COMMENT_PREFIX, roadmap_stage_ids))
    return "\n".join(parts)
