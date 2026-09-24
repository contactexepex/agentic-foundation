"""Config-text builders — the commented YAML stage snippets that make up the generated file."""
from __future__ import annotations

from typing import Any

from ..render import (
    GATE_ADVISORY,
    GATE_BLOCKING,
)

from .defaults import (
    _DOCS_CHARTER,
    _PROFILE_STAGES,
    _ROADMAP_STAGE_PROVIDER,
    _ROADMAP_STAGES,
    _canonical_gate,
)


# --------------------------------------------------------------------------- stage snippets

_IMPLEMENT_SNIPPET = """\
  # Implementer — Claude addresses review findings (manual/dispatch entry point).
  - id: implement
    type: implement
    provider: anthropic
    triggers: [manual]"""

def _review_snippet(gate: str) -> str:
    # "blocking" means a finding posts a review thread that the merge gate treats as unresolved.
    # The enforcing gate (the foundation auto-merge gate / branch protection) is the operator's to
    # enable and is roadmap in stagr's rendered output (CHARTER §7), so this is worded as intent,
    # not a claim that stagr itself blocks the merge today.
    note = ("blocking: findings block via review threads (enforced by the merge gate / branch "
            "protection — roadmap, CHARTER §7)" if gate == GATE_BLOCKING
            else "advisory: reports, does not block")
    return (
        f"  # Reviewer — Codex code review ({note}).\n"
        "  - id: review\n"
        "    type: review\n"
        "    provider: openai            # OpenAI/Codex is the rendered reviewer (tool derived from provider)\n"
        "    skill: code-review          # built-in; override with your own via the `skills:` registry\n"
        f"    gate: {gate}\n"
        # On PR open the Codex app reviews natively (that is what services `pr_opened`); stagr's
        # rendered workflow re-requests a review on each push (`pr_updated`), which Codex does not
        # auto-handle.
        "    triggers: [pr_opened, pr_updated]   # pr_opened: Codex app reviews on open; "
        "pr_updated: stagr re-requests per push"
    )

# A `custom` profile has no stages yet — define your own. Left fully commented so the file is valid
# as-is; uncomment and edit. Each stage is one agent step; `type` drives sensible defaults.
_CUSTOM_SKELETON = """\
# Define your pipeline here (this block is commented so the config is valid until you fill it in).
# Stage types: plan | implement | review | security | test | integration-test | docs | release | custom
# Example — Claude implementer + Codex code review (the tool is derived from `provider`):
# stages:
#   - id: implement
#     type: implement
#     provider: anthropic
#     triggers: [manual]
#   - id: review
#     type: review
#     provider: openai
#     skill: code-review
#     gate: blocking
#     triggers: [pr_opened, pr_updated]"""


def _security_snippet(blocking: bool) -> str:
    gate = GATE_BLOCKING if blocking else GATE_ADVISORY
    # A security finding blocks the PR by posting a review thread (the merge gate requires zero
    # unresolved threads). Gating on security-review *completion* (blocking even a clean review
    # until it finishes) is roadmap — CHARTER §7 — so "blocking" here means findings block today,
    # not that merge waits for the review to complete.
    note = ("blocking: findings block via review threads; completion-gating is roadmap (CHARTER §7)"
            if blocking else "advisory: reports, does not block")
    return (
        f"  # Security reviewer — Codex security review ({note}).\n"
        "  - id: security\n"
        "    type: security\n"
        "    provider: openai            # OpenAI/Codex is the rendered reviewer (tool derived from provider)\n"
        "    skill: security-review      # built-in; override via the `skills:` registry\n"
        f"    gate: {gate}\n"
        # UNLIKE the code review, the security review runs ONCE as the final pre-merge step
        # (final-security-review.yml), after the code review converges — never on open and never per
        # push — so it never races the code review (Codex's backend errors on a concurrent pair). These
        # triggers only select the security lane; configure the Codex App to auto-run the CODE review
        # only on open (a ChatGPT-side setting the toolkit cannot render), or its native security review
        # will race the code review on every open.
        "    triggers: [pr_opened, pr_updated]   # selects the security lane; the review itself runs "
        "once, after the code review (final-security-review.yml)"
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
        commented = "\n".join(f"  # - {{ id: {s}, type: {s}, provider: {_ROADMAP_STAGE_PROVIDER[s]} }}" for s in roadmap)
        parts.append(
            "  # Declared but NOT yet rendered to workflows (multi-stage rendering is roadmap —\n"
            f"  # {_DOCS_CHARTER} §7). Uncomment to declare intent; `stagr plan` shows what renders.\n"
            + commented
        )
    return "\n".join(parts)
