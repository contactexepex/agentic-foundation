"""Workflow lane selection: decide which Codex review/security lanes a stage graph needs,
reject unsupported review graphs, and drive the `LANES` registry that picks templates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .constants import BACKEND_CODEX, GATE_ADVISORY, GATE_BLOCKING
from .errors import RenderError
from .models import _stage_backend

# A stage's `gate` defaults from its type when omitted (schema: review/security/test default to
# blocking; everything else to advisory). Only a BLOCKING stage becomes a merge requirement.
_BLOCKING_DEFAULT_TYPES = frozenset({"review", "security", "test", "integration-test"})


def _effective_gate(stage: dict[str, Any]) -> str:
    gate = stage.get("gate")
    if gate in (GATE_ADVISORY, GATE_BLOCKING):
        return gate
    return GATE_BLOCKING if stage.get("type") in _BLOCKING_DEFAULT_TYPES else GATE_ADVISORY


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
# The fail-closed auto-merge gate: merges a provably-ready PR (green CI + head-bound Codex review/
# security when configured + clean review + operator-named external checks; `human-merge` label is a
# hard stop). Emitted when `modules.auto_merge` is enabled — a MODULE toggle, not a stage, so its
# lane predicate reads the config, not just the stage graph.
AUTO_MERGE_TEMPLATE = "auto-merge.yml.tmpl"


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


def _auto_merge_enabled(cfg: dict[str, Any]) -> bool:
    # The auto-merge gate renders when the `auto_merge` module is on (opt-in; off by default so the
    # unconfigured default stays human-merge). It is a config toggle, independent of the stage graph.
    return bool((cfg.get("modules") or {}).get("auto_merge"))


def _requires_codex_code_review(stages: list[dict[str, Any]]) -> bool:
    # The auto-merge gate demands a head-bound Codex CODE review only for a BLOCKING codex review stage
    # that runs on pushed heads. An advisory review is comment-only (never a merge blocker), and a
    # pr_opened-only review does not cover pushed heads (rejected by _ensure_auto_merge_coherent).
    return any(_effective_gate(s) == GATE_BLOCKING and _wants_push_review(s)
               for s in _codex_stages(stages, "review"))


def _requires_codex_security_review(stages: list[dict[str, Any]]) -> bool:
    # The gate demands the head-bound final security review only for a BLOCKING codex security stage
    # that takes part in PR review (advisory security is comment-only, never a merge blocker).
    return any(_effective_gate(s) == GATE_BLOCKING and _runs_on_pr_review(s)
               for s in _codex_stages(stages, "security"))


def _ensure_auto_merge_coherent(stages: list[dict[str, Any]], cfg: dict[str, Any]) -> None:
    """Reject auto-merge configs whose gate requirement could never be satisfied (a silent deadlock).

    Only checked when `modules.auto_merge` is on. Both cases arise because auto-merge merges PUSHED
    heads and the gate requires a head-bound Codex review for a blocking review stage:

    * A BLOCKING codex `review` stage that runs only on `pr_opened` cannot review a pushed head, yet
      auto-merge would merge one — so it would merge un-reviewed code. Require `pr_updated`.
    * With the fast path enabled, a trivial PR is fast-path-approved with NO Codex review, but the gate
      still requires one — so that PR could never merge. Require `routing.fast_path.enabled: false`
      whenever the gate requires a Codex review (this is why the toolkit's own repo disables it).
    """
    if not _auto_merge_enabled(cfg):
        return
    # (a) Every BLOCKING stage must yield a gate signal the auto-merge gate actually verifies. Today
    # that is only the Codex code review and Codex security review (alongside CI/Validate and
    # merge.required_status_checks). A blocking stage of any other type — test, integration-test, docs,
    # a non-Codex review, an explicitly-blocking implement, ... — renders no merge signal yet, so
    # auto-merging would silently bypass a declared blocking gate. Reject it.
    for stage in stages:
        if _effective_gate(stage) != GATE_BLOCKING:
            continue
        stage_type = stage.get("type")
        covered = (stage_type in ("review", "security")
                   and _stage_backend(stage) == BACKEND_CODEX
                   and _runs_on_pr_review(stage))
        if not covered:
            raise RenderError(
                f"modules.auto_merge cannot enforce the blocking stage '{stage.get('id')}' (type "
                f"'{stage_type}'): the auto-merge gate verifies only Codex code/security reviews that "
                "take part in PR review (pr_opened / pr_updated) — plus CI/Validate and "
                "merge.required_status_checks. A stage of another type, a non-Codex backend, or one whose "
                "triggers omit a PR-review event renders no merge signal, so it would be silently "
                "dropped. Make it advisory, give it a PR-review trigger, or disable auto_merge."
            )
    # (b) A blocking Codex 'review' OR 'security' stage must cover PUSHED heads (auto-merge merges pushed
    # heads and the gate requires a head-bound Codex review/security for it). A pr_opened-only stage can't:
    #   - 'review': a pushed head would merge un-reviewed.
    #   - 'security': the final security review runs only AFTER the code review converges on the SAME head
    #     (final-security-review.yml waits for the code review's "Completed" row), so on a pushed head it
    #     is head-bound only if the code review re-runs there — which needs a pr_updated code-review stage.
    #     Requiring pr_updated on the blocking security stage forces the code-review stage onto pushed
    #     heads too, via the trigger-equality rule in _ensure_supported_review_graph.
    # Require pr_updated either way. (_runs_on_pr_review excludes non-PR stages already caught by (a), so
    # a manual/comment-only stage raises the clearer (a) error, not this one.)
    _pushed_head_rationale = {
        "review": "a review that runs only on 'pr_opened' would let an un-reviewed pushed head merge",
        "security": ("the final security review runs only after the code review converges on the same "
                     "head, so a security stage that runs only on 'pr_opened' can never yield a "
                     "head-bound security review for the pushed head auto-merge would merge"),
    }
    for stage_type, why in _pushed_head_rationale.items():
        for stage in _codex_stages(stages, stage_type):
            if _effective_gate(stage) == GATE_BLOCKING and _runs_on_pr_review(stage) and not _wants_push_review(stage):
                raise RenderError(
                    f"modules.auto_merge with a blocking Codex '{stage_type}' stage requires that stage "
                    "to run on pushed heads: add 'pr_updated' to its triggers. auto-merge merges pushed "
                    f"heads and the gate requires a head-bound Codex {stage_type} review, but {why}."
                )
    # (c) When the gate requires ANY Codex review — code OR security is blocking — the fast path must be
    # off. A fast-path-approved trivial PR gets no Codex review (and the security review runs only after
    # the code review converges), so the gate could never merge it. Applies to a blocking security stage
    # even with an advisory code-review stage.
    fast_path_enabled = ((cfg.get("routing", {}) or {}).get("fast_path", {}) or {}).get("enabled", True)
    if (_requires_codex_code_review(stages) or _requires_codex_security_review(stages)) and fast_path_enabled:
        raise RenderError(
            "modules.auto_merge with a blocking Codex review or security stage requires "
            "routing.fast_path.enabled: false. With the fast path on, a trivial PR is fast-path-"
            "approved with no Codex review, yet the auto-merge gate requires a head-bound Codex review "
            "— so that PR could never merge. Disable the fast path (every PR is reviewed) when "
            "auto-merging with a Codex review or security stage."
        )


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
    applies: Callable[[list[dict[str, Any]], dict[str, Any]], bool]
    templates: tuple[str, ...]


# The lane registry, in emit order. `core` (the repo's "green" check + review router) always applies;
# each other lane renders only when its condition holds. A lane predicate receives BOTH the expanded
# stage graph and the full config, so a stage-driven lane reads `stages` and a module-driven lane (e.g.
# auto-merge) reads `cfg` — `LANES` stays the single place a lane is wired in (CHARTER §7).
LANES: tuple[Lane, ...] = (
    Lane("core", lambda stages, cfg: True, tuple(CORE_TEMPLATES)),
    Lane("implementor", lambda stages, cfg: _has_implement_stage(stages), (IMPLEMENTOR_TEMPLATE,)),
    Lane("codex-code-review", lambda stages, cfg: _has_codex_code_review(stages), (CODE_REVIEW_TEMPLATE,)),
    Lane("codex-security-review", lambda stages, cfg: _has_codex_security_review(stages), (SECURITY_REVIEW_TEMPLATE,)),
    Lane("codex-threads", lambda stages, cfg: _has_codex_push_review(stages), (RESOLVE_THREADS_TEMPLATE,)),
    Lane("auto-merge", lambda stages, cfg: _auto_merge_enabled(cfg), (AUTO_MERGE_TEMPLATE,)),
)


def select_templates(stages: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> list[str]:
    """Choose which workflow templates to emit, driven by the `LANES` registry (emit order).

    `cfg` is optional for backward compatibility (a caller passing only `stages` gets the stage-driven
    lanes; module-driven lanes such as auto-merge need `cfg`).
    """
    cfg = cfg or {}
    _ensure_supported_review_graph(stages)
    _ensure_auto_merge_coherent(stages, cfg)
    names: list[str] = []
    for lane in LANES:
        if lane.applies(stages, cfg):
            names.extend(lane.templates)
    return names
