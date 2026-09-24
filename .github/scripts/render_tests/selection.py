"""Pipeline/lane selection tests (which workflows are emitted for a given config)."""
from __future__ import annotations

import re

from .harness import REPO_ROOT, check, expect_raises, render


def test_pipeline_selection() -> None:
    # A codex-backed review/security stage -> the review lane is emitted.
    cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    rendered = render.render_all(cfg, "github")
    for name in ("validate.yml", "review-router.yml", "implementor.yml",
                 "request-review.yml", "final-security-review.yml", "resolve-threads.yml"):
        check(name in rendered, f"select: {name} emitted for codex-review config")
    # The codex PAT is referenced by NAME (from platform.auth.token_secret), never a value.
    check("secrets.REMEDIATION_TOKEN" in rendered["request-review.yml"],
          "select: codex_review_secret NAME substituted into request-review")
    check(not re.search(r"ghp_[A-Za-z0-9]{8,}", rendered["resolve-threads.yml"]),
          "select: resolve-threads inlines no secret value")
    # Regression (#15): the on-push lane re-triggers a head stranded during a long security review.
    # It must carry the extra event triggers (issue_comment:edited + check_suite:completed, never
    # :created) and the per-head stranding marker, so the re-trigger path can't be silently dropped.
    _rev = rendered["request-review.yml"]
    check("issue_comment" in _rev and "check_suite" in _rev
          and "code-review-requested:" in _rev,
          "select: request-review carries the stranded-head re-trigger + marker (#15)")

    # No codex review stage -> the review lane is NOT emitted (module-aware, not glob-all).
    minimal = {"version": 2, "profile": "custom",
               "platform": {"type": "github", "default_branch": "main"},
               "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "c"}}},
               "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}]}
    r2 = render.render_all(minimal, "github")
    check("request-review.yml" not in r2 and "resolve-threads.yml" not in r2,
          "select: no review lane without a codex review stage")
    check("validate.yml" in r2, "select: core pipeline still emitted")

    # No implement stage -> implementor.yml is NOT emitted (it would carry an empty model and a
    # provider key the graph never uses); the review lane still renders for the review stage.
    review_only = {"version": 2, "profile": "custom",
                   "platform": {"type": "github", "default_branch": "main"},
                   "defaults": {"provider": "openai", "models": {}},
                   "stages": [{"id": "review", "type": "review", "provider": "openai",
                               "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]}]}
    r3 = render.render_all(review_only, "github")
    check("implementor.yml" not in r3, "select: no implementor.yml without an implement stage")
    check("validate.yml" in r3 and "request-review.yml" in r3,
          "select: core + review lane still emitted for a review-only graph")

    # Split lanes: a code-review-only graph renders the on-push code lane (request-review.yml) and
    # NEVER the security lane; the code lane posts only `@codex review`.
    code_only = {"version": 2, "profile": "custom",
                 "platform": {"type": "github", "default_branch": "main"},
                 "defaults": {"provider": "openai", "models": {}},
                 "stages": [{"id": "review", "type": "review", "provider": "openai",
                             "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]}]}
    r_code = render.render_all(code_only, "github")
    check("post_codex '@codex review'" in r_code["request-review.yml"]
          and "@codex security review" not in r_code["request-review.yml"],
          "request-review: posts only the code review, never security")
    check("final-security-review.yml" not in r_code,
          "select: no security lane without a codex security stage")

    # A codex security stage WITHOUT a codex code-review stage is rejected: the security review runs
    # only after the code review converges, so a security-only graph would render a workflow that can
    # never fire. Fail loud at both the render path and the validation front door.
    security_only = {"version": 2, "profile": "custom",
                     "platform": {"type": "github", "default_branch": "main"},
                     "defaults": {"provider": "openai", "models": {}},
                     "stages": [{"id": "security", "type": "security", "provider": "openai",
                                 "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]}]}
    expect_raises(lambda: render.render_all(security_only, "github"),
                  "select: codex security stage without a code-review stage fails loud (render)")
    expect_raises(lambda: render.validate_config(security_only),
                  "validate: codex security stage without a code-review stage fails loud (front door)")

    # A codex review+security graph triggered only on pr_opened (no pr_updated) still renders the final
    # security lane: the security review runs once after the code review converges, not per push. The
    # on-push code re-request lane (request-review.yml) is correctly absent (nothing wants pr_updated).
    pr_opened_only = {"version": 2, "profile": "custom",
                      "platform": {"type": "github", "default_branch": "main"},
                      "defaults": {"provider": "openai", "models": {}},
                      "stages": [{"id": "review", "type": "review", "provider": "openai",
                                  "backend": {"name": "codex"}, "triggers": ["pr_opened"]},
                                 {"id": "security", "type": "security", "provider": "openai",
                                  "backend": {"name": "codex"}, "triggers": ["pr_opened"]}]}
    r_open = render.render_all(pr_opened_only, "github")
    check("final-security-review.yml" in r_open,
          "select: final security lane renders for a pr_opened-only security stage")
    check("request-review.yml" not in r_open and "resolve-threads.yml" not in r_open,
          "select: on-push lanes absent when no stage requests pr_updated")

    # doctor must report the PAT whenever a request/cleanup workflow renders — including a pr_opened-only
    # security graph that renders final-security-review.yml (which reads the PAT) but no on-push lane.
    check(render._needs_codex_pat(render.expand_stages(pr_opened_only)),
          "select: PAT is required for a pr_opened-only security graph (doctor must report it)")

    # Code/security PR triggers must be EQUAL: the final security review renders as one event-agnostic
    # workflow (fires whenever the code review converges), so it cannot honour a narrower or wider set.
    # (a) superset — security runs on an event with no converged code review behind it:
    sec_superset = {"version": 2, "profile": "custom",
                    "platform": {"type": "github", "default_branch": "main"},
                    "defaults": {"provider": "openai", "models": {}},
                    "stages": [{"id": "review", "type": "review", "provider": "openai",
                                "backend": {"name": "codex"}, "triggers": ["pr_opened"]},
                               {"id": "security", "type": "security", "provider": "openai",
                                "backend": {"name": "codex"}, "triggers": ["pr_updated"]}]}
    expect_raises(lambda: render.render_all(sec_superset, "github"),
                  "select: security trigger not covered by code review fails loud (render)")
    expect_raises(lambda: render.validate_config(sec_superset),
                  "validate: security trigger not covered by code review fails loud (front door)")
    # (b) subset — security narrower than code review would still fire on the code review's other events:
    sec_subset = {"version": 2, "profile": "custom",
                  "platform": {"type": "github", "default_branch": "main"},
                  "defaults": {"provider": "openai", "models": {}},
                  "stages": [{"id": "review", "type": "review", "provider": "openai",
                              "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]},
                             {"id": "security", "type": "security", "provider": "openai",
                              "backend": {"name": "codex"}, "triggers": ["pr_updated"]}]}
    expect_raises(lambda: render.render_all(sec_subset, "github"),
                  "select: security triggers narrower than code review fail loud (render)")
    expect_raises(lambda: render.validate_config(sec_subset),
                  "validate: security triggers narrower than code review fail loud (front door)")

    # The dogfood config has a codex security stage -> the security review is requested ONLY from the
    # final-security-review lane (never alongside the code review), so the two never run concurrently.
    check("@codex security review" in rendered["final-security-review.yml"],
          "final-security-review: requests the security review")
    check("@codex security review" not in rendered["request-review.yml"],
          "request-review: never requests the security review (moved to the final lane)")

    # The lane registry is the single selection seam (names, in emit order).
    check([lane.name for lane in render.LANES]
          == ["core", "implementor", "codex-code-review", "codex-security-review", "codex-threads"],
          "select: LANES registry drives template selection, in emit order")
