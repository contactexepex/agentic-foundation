"""Workflow lane selection: decide which Codex review/security lanes a stage graph needs,
reject unsupported review graphs, and drive the `LANES` registry that picks templates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .constants import BACKEND_CODEX
from .errors import RenderError
from .models import _stage_backend


# The always-emitted core: the repo's "green" check and the review router that classifies each
# change. The implementer entry point is emitted separately, only when an implement stage exists
# (otherwise implementor.yml would carry an empty model and reference a key the graph never needs).
CORE_TEMPLATES = ["validate.yml.tmpl", "review-router.yml.tmpl"]
IMPLEMENTOR_TEMPLATE = "implementor.yml.tmpl"
# The codex code-review lane: re-request a code review of each pushed head, so review iterates as the
# PR is updated. Emitted when a codex-backed review stage runs on pushed heads.
CODE_REVIEW_TEMPLATE = "request-review.yml.tmpl"
# The codex security-review lane: request ONE security review as the final pre-merge step, once the
# code review has converged — never concurrent with the code review (Codex errors on a concurrent
# pair). Emitted when a codex-backed security stage runs on pushed heads.
SECURITY_REVIEW_TEMPLATE = "final-security-review.yml.tmpl"
# Auto-resolve outdated Codex threads. Emitted whenever any codex review/security lane runs.
RESOLVE_THREADS_TEMPLATE = "resolve-threads.yml.tmpl"


def _wants_push_review(stage: dict[str, Any]) -> bool:
    """True if a review/security stage should run on each pushed head.

    A stage with no explicit `triggers` defaults to reviewing PR updates. A stage that lists
    triggers but omits `pr_updated` (e.g. only `manual` / `comment_command`) must NOT get the
    synchronize-triggered request workflow — otherwise paid reviews fire on events the stage
    never authorized.
    """
    trig = stage.get("triggers")
    if trig is None:
        return True
    return "pr_updated" in trig


def _has_implement_stage(stages: list[dict[str, Any]]) -> bool:
    # The implementer workflow is emitted only when the graph actually has an implement stage;
    # without one it would render with an empty model and a provider key the pipeline never uses.
    return any(stage.get("type") == "implement" for stage in stages)


def _runs_on_pr_review(stage: dict[str, Any]) -> bool:
    """True if a review/security stage takes part in the PR review lifecycle (open and/or update).

    Unlike `_wants_push_review` (which gates the per-push re-request lane on `pr_updated`), this is
    also true for `pr_opened`. The final security review runs once as a post-code-review step, not per
    push, so its lane must render whenever the security stage participates in PR review at all — a
    `pr_opened`-only security stage still needs the final-security-review workflow.
    """
    trig = stage.get("triggers")
    if trig is None:
        return True
    return "pr_opened" in trig or "pr_updated" in trig


def _codex_stages(stages: list[dict[str, Any]], stage_type: str) -> list[dict[str, Any]]:
    return [s for s in stages if s.get("type") == stage_type and _stage_backend(s) == BACKEND_CODEX]


_PR_REVIEW_EVENTS = frozenset({"pr_opened", "pr_updated"})


def _pr_review_triggers(stage: dict[str, Any]) -> set[str]:
    """The PR-review events (pr_opened / pr_updated) a stage takes part in. No explicit `triggers`
    defaults to both (see `_runs_on_pr_review`)."""
    trig = stage.get("triggers")
    if trig is None:
        return set(_PR_REVIEW_EVENTS)
    return _PR_REVIEW_EVENTS & set(trig)


def _has_codex_code_review(stages: list[dict[str, Any]]) -> bool:
    # request-review.yml (the on-push re-request lane) renders when a codex CODE review stage runs on
    # each pushed head (`pr_updated`); a pr_opened-only code review is handled by the App on open.
    return any(_wants_push_review(s) for s in _codex_stages(stages, "review"))


def _has_codex_security_review(stages: list[dict[str, Any]]) -> bool:
    # final-security-review.yml renders whenever a codex SECURITY stage takes part in PR review
    # (pr_opened and/or pr_updated). The review itself runs once, after the code review converges — it
    # is NOT a per-push lane — so it must render for a pr_opened-only security stage too.
    return any(_runs_on_pr_review(s) for s in _codex_stages(stages, "security"))


def _has_codex_push_review(stages: list[dict[str, Any]]) -> bool:
    # resolve-threads.yml renders when the on-push code-review lane runs: only a pushed head creates
    # outdated review threads to clean up. (The security review is not a per-push lane.)
    return _has_codex_code_review(stages)


def _needs_codex_pat(stages: list[dict[str, Any]]) -> bool:
    # The real-user PAT authors every rendered Codex request/cleanup workflow — request-review.yml
    # (code on-push), final-security-review.yml (the security lane), and resolve-threads.yml — so it is
    # required whenever ANY of them render, including a pr_opened-only security graph that renders the
    # security lane but no on-push lane.
    return _has_codex_code_review(stages) or _has_codex_security_review(stages)


def _ensure_supported_review_graph(stages: list[dict[str, Any]]) -> None:
    """Reject a Codex security lane that could never fire or would be orchestrated incoherently.

    The final security review runs ONLY after the Codex code review converges on the same head
    (final-security-review.yml waits for the code review's "Completed" row before requesting it). So:

    * A Codex `security` stage with no Codex `review` stage would render a security workflow that no
      event can ever satisfy — reject it.
    * A Codex `security` stage that runs on a PR event the code-review stage does NOT run on is
      incoherent: on that event there is no code review to converge behind (e.g. code review only on
      `pr_opened` but security on `pr_updated` — pushed heads get no code re-review, so security can
      never unlock). Require the security stage's PR triggers to be covered by the code-review stage's.

    Fail loud at the front door so an unsupported graph is a clear error, not a dead or mis-wired lane.
    """
    security_stages = [s for s in _codex_stages(stages, "security") if _runs_on_pr_review(s)]
    if not security_stages:
        return
    code_stages = [s for s in _codex_stages(stages, "review") if _runs_on_pr_review(s)]
    if not code_stages:
        raise RenderError(
            "a Codex security-review stage requires a Codex code-review ('review') stage: the security "
            "review runs only after the code review has converged, so a security stage on its own would "
            "render a workflow that never fires. Add a codex-backed 'review' stage, or remove the "
            "'security' stage."
        )
    code_triggers: set[str] = set().union(*(_pr_review_triggers(s) for s in code_stages))
    for sec in security_stages:
        sec_triggers = _pr_review_triggers(sec)
        if sec_triggers != code_triggers:
            raise RenderError(
                "a Codex security-review stage must run on exactly the same PR triggers as its Codex "
                "code-review ('review') stage. The final security review renders as a single, "
                "event-agnostic workflow that fires whenever the code review converges on the head, so "
                "it cannot honour a narrower or wider trigger set — a subset would still run security on "
                "events the stage did not request, a superset would have no code review to converge "
                f"behind. Security triggers {sorted(sec_triggers)} != code-review triggers "
                f"{sorted(code_triggers)}; set them equal (or omit triggers on both to default to "
                "pr_opened+pr_updated)."
            )


@dataclass(frozen=True)
class Lane:
    """One rendered workflow lane: its `templates` are emitted when `applies` holds for the
    fully-expanded stage graph. `LANES` is the single place a lane is wired in, so a future lane
    (multi-stage gates, other platforms — CHARTER §7) is one entry here, not another branch.
    """

    name: str
    applies: Callable[[list[dict[str, Any]]], bool]
    templates: tuple[str, ...]


# The lane registry, in emit order. `core` (the repo's "green" check + review router) always
# applies; each other lane is module-aware and renders only when a matching stage exists. (The
# `modules.auto_merge` gate is intentionally not a lane yet — its trust model is under review; see
# PR #2 — so an auto_merge config still renders its core pipeline.)
LANES: tuple[Lane, ...] = (
    Lane("core", lambda stages: True, tuple(CORE_TEMPLATES)),
    Lane("implementor", _has_implement_stage, (IMPLEMENTOR_TEMPLATE,)),
    Lane("codex-code-review", _has_codex_code_review, (CODE_REVIEW_TEMPLATE,)),
    Lane("codex-security-review", _has_codex_security_review, (SECURITY_REVIEW_TEMPLATE,)),
    Lane("codex-threads", _has_codex_push_review, (RESOLVE_THREADS_TEMPLATE,)),
)


def select_templates(stages: list[dict[str, Any]]) -> list[str]:
    """Choose which workflow templates to emit, driven by the `LANES` registry (emit order)."""
    _ensure_supported_review_graph(stages)
    names: list[str] = []
    for lane in LANES:
        if lane.applies(stages):
            names.extend(lane.templates)
    return names
