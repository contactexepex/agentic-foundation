"""Pipeline/lane selection tests (which workflows are emitted for a given config)."""
from __future__ import annotations

import re

from .harness import REPO_ROOT, check, expect_raises, render

# The final security review is requested with this exact slash command; referenced in several
# assertions, so name it once (avoids a duplicated-literal smell and keeps the command in one place).
_SEC_REVIEW_CMD = "@codex security review"


def _check_dogfood_lane_emission(rendered: dict) -> None:
    """All expected lanes are emitted for the dogfood config; no secret values are inlined."""
    for name in ("validate.yml", "review-router.yml", "implementor.yml",
                 "request-review.yml", "final-security-review.yml", "resolve-threads.yml",
                 "auto-merge.yml"):
        check(name in rendered, f"select: {name} emitted for codex-review config")
    check("secrets.REMEDIATION_TOKEN" in rendered["request-review.yml"],
          "select: codex_review_secret NAME substituted into request-review")
    check(not re.search(r"ghp_[A-Za-z0-9]{8,}", rendered["resolve-threads.yml"]),
          "select: resolve-threads inlines no secret value")
    rev = rendered["request-review.yml"]
    check("issue_comment" in rev and "check_suite" in rev and "code-review-requested:" in rev,
          "select: request-review carries the stranded-head re-trigger + marker (#15)")


def _check_final_security_review_triggers(rendered: dict) -> None:
    """Final-security-review triggers are exactly issue_comment/check_suite/schedule (#25/#26)."""
    sec = rendered["final-security-review.yml"]
    sec_on = sec.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    triggers = set(re.findall(r"^ {2}([a-z_]+):", sec_on, re.M))
    check(triggers == {"issue_comment", "check_suite", "schedule"},
          f"select: final-security-review triggers are exactly issue_comment/check_suite/schedule (got {sorted(triggers)})")
    check("group: request-codex-security\n" in sec and "cancel-in-progress: false" in sec,
          "select: final-security-review serializes on one global concurrency group (#26 race)")
    check(_SEC_REVIEW_CMD in sec, "select: final-security-review requests the security review")
    check("grep -qi 'Completed'" in sec, "select: gate requires the code-review row Completed on the head")
    check('[[ "$unresolved" == "0" ]]' in sec, "select: gate requires zero unresolved threads before security")


def _check_minimal_config_lane_selection(minimal: dict) -> None:
    """No review lane without a codex review stage; auto-merge off by default."""
    r2 = render.render_all(minimal, "github")
    check("request-review.yml" not in r2 and "resolve-threads.yml" not in r2,
          "select: no review lane without a codex review stage")
    check("validate.yml" in r2, "select: core pipeline still emitted")
    check("auto-merge.yml" not in r2, "select: no auto-merge lane when modules.auto_merge is off")


def _check_auto_merge_implement_only_graph(minimal: dict) -> None:
    """auto_merge: true on an implement-only graph renders the gate without requiring Codex reviews."""
    auto = {**minimal, "modules": {"auto_merge": True}}
    r_auto = render.render_all(auto, "github")
    am = r_auto.get("auto-merge.yml", "")
    check("auto-merge.yml" in r_auto, "select: auto-merge lane emitted when modules.auto_merge is on")
    check('REQUIRE_CODEX_CODE_REVIEW: "false"' in am
          and 'REQUIRE_CODEX_SECURITY_REVIEW: "false"' in am,
          "auto-merge: implement-only graph does not require a Codex review (no deadlock)")
    check("REQUIRED_STATUS_CHECKS: '[]'" in am,
          "auto-merge: no external checks required without merge.required_status_checks")


def _check_auto_merge_blocking_codex_review_requirements() -> None:
    """Blocking codex review+security with auto_merge: gate requires both head-bound reviews."""
    blocking_review_config = {
        "version": 2, "profile": "custom",
        "platform": {"type": "github", "default_branch": "main",
                     "auth": {"token_secret": "REMEDIATION_TOKEN"}},
        "defaults": {"provider": "openai", "models": {}},
        "modules": {"auto_merge": True},
        "merge": {"required_status_checks": [{"name": "SonarCloud Code Analysis", "app_id": 12345},
                                             {"name": "Checkmarx One", "app_id": 678}],
                  "method": "merge"},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"}, "gate": "blocking",
                    "triggers": ["pr_opened", "pr_updated"]},
                   {"id": "security", "type": "security", "backend": {"name": "codex"}, "gate": "blocking",
                    "triggers": ["pr_opened", "pr_updated"]}],
    }
    amq = render.render_all(blocking_review_config, "github")["auto-merge.yml"]
    check("SonarCloud Code Analysis" in amq and "Checkmarx One" in amq,
          "auto-merge: merge.required_status_checks names rendered tool-agnostically")
    check('"app_id": 12345' in amq and '"app_id": 678' in amq,
          "auto-merge: external checks carry the producing App id (positive identity)")
    check(".app.id==$aid" in amq and '!="github-actions"' not in amq,
          "auto-merge: external checks matched by name AND app.id, not a negative not-github-actions rule")
    check('REQUIRE_CODEX_CODE_REVIEW: "true"' in amq
          and 'REQUIRE_CODEX_SECURITY_REVIEW: "true"' in amq,
          "auto-merge: blocking codex review+security graph requires both head-bound reviews")
    check("-f merge_method=merge " in amq, "auto-merge: merge.method rendered into the merge call")
    check("group_by([.app.id, .name])" in amq and "sort_by(.id) | last" in amq,
          "auto-merge: check-runs identity is (app.id,name), latest attempt by id (no stale-green fallback)")
    check(amq.count('gates_pass "$pr"') >= 2,
          "auto-merge: every gate is re-evaluated (gates_pass called twice before merge)")
    check("path_is_protected" in amq and ".github/workflows" in amq and "MERGE_PROTECTED_PATHS" in amq,
          "auto-merge: control-plane guard present with default protected paths")
    check('test("Codex Review")' in amq and "codex-security-review" in amq,
          "auto-merge: Codex code-review body marker + full-SHA security marker used")
    check("pull_request_target" in amq and "\n  pull_request:\n" not in amq,
          "auto-merge: runs on pull_request_target, never pull_request (P0)")
    check("actions/checkout" not in amq,
          "auto-merge: never checks out PR content (P0)")
    check(not re.search(r"ghp_[A-Za-z0-9]{8,}", amq), "auto-merge: inlines no secret value")
    check('per_page=100" --slurp' in amq and "map(.statuses)" in amq,
          "auto-merge: combined status is paginated before context lookup")
    check('-f "base=$DEFAULT_BRANCH"' in amq,
          "auto-merge: default branch passed as an encoded GET param")


def _check_auto_merge_advisory_and_deadlock_guards(advisory_config: dict) -> None:
    """Advisory codex review is not a merge requirement; deadlock configs are rejected."""
    am_adv = render.render_all(advisory_config, "github")["auto-merge.yml"]
    check('REQUIRE_CODEX_CODE_REVIEW: "false"' in am_adv,
          "auto-merge: an advisory codex review is not a merge requirement (#5)")

    # blocking review + fast_path ON -> deadlock
    fast_path_on = {**advisory_config, "stages": [
        {"id": "review", "type": "review", "backend": {"name": "codex"},
         "gate": "blocking", "triggers": ["pr_opened", "pr_updated"]},
    ]}
    expect_raises(lambda: render.render_all(fast_path_on, "github"),
                  "auto-merge: blocking review + fast_path enabled fails loud (deadlock) (#2, render)")
    expect_raises(lambda: render.validate_config(fast_path_on),
                  "auto-merge: blocking review + fast_path enabled fails loud (#2, front door)")

    # blocking review triggered only on pr_opened -> cannot gate pushed heads
    pr_opened_only_blocking = {**advisory_config, "routing": {"fast_path": {"enabled": False}},
                               "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                                           "gate": "blocking", "triggers": ["pr_opened"]}]}
    expect_raises(lambda: render.render_all(pr_opened_only_blocking, "github"),
                  "auto-merge: blocking pr_opened-only review fails loud (unreviewed pushed heads) (#4, render)")
    expect_raises(lambda: render.validate_config(pr_opened_only_blocking),
                  "auto-merge: blocking pr_opened-only review fails loud (#4, front door)")

    # Various invalid config guards
    _check_auto_merge_config_validity_guards(advisory_config)


def _check_required_check_and_merge_method_guards(advisory_config: dict) -> None:
    """Required-check name/app_id validity, merge method, and human-merge label safety."""
    empty_check = {**advisory_config, "routing": {"fast_path": {"enabled": False}},
                   "merge": {"required_status_checks": [{"name": "", "app_id": 1}]}}
    expect_raises(lambda: render.render_all(empty_check, "github"),
                  "auto-merge: empty required-check name fails loud (#6, render)")
    expect_raises(lambda: render.validate_config(empty_check),
                  "auto-merge: empty required-check name fails loud (#6, schema)")
    expect_raises(lambda: render.validate_config({**advisory_config, "routing": {"fast_path": {"enabled": False}},
                  "merge": {"required_status_checks": [{"name": "X"}]}}),
                  "auto-merge: required check without app_id fails loud (schema)")
    expect_raises(lambda: render.validate_config({**advisory_config, "routing": {"fast_path": {"enabled": False}},
                  "merge": {"required_status_checks": [{"name": "X", "app_id": 0}]}}),
                  "auto-merge: required check app_id < 1 fails loud (schema)")
    expect_raises(lambda: render.render_all({**advisory_config, "routing": {"fast_path": {"enabled": False}},
                  "merge": {"required_status_checks": [{"name": "${{ github.token }}", "app_id": 1}]}}, "github"),
                  "auto-merge: ${{ }} in a required-check name fails loud (render)")
    expect_raises(lambda: render.render_all({**advisory_config, "merge": {"method": "fast-forward"}}, "github"),
                  "auto-merge: unknown merge.method fails loud (#9, render)")
    expect_raises(lambda: render.validate_config({**advisory_config, "merge": {"method": "fast-forward"}}),
                  "auto-merge: unknown merge.method fails loud (#9, schema)")
    expect_raises(lambda: render.render_all(
        {**advisory_config, "platform": {"type": "github", "default_branch": "main",
                                         "auth": {"token_secret": "REMEDIATION_TOKEN"},
                                         "labels": {"human_merge": 'ho"ld'}}}, "github"),
        "auto-merge: unsafe human_merge label fails loud (#7-label)")


def _check_blocking_security_and_unsupported_stage_guards() -> None:
    """Blocking security with fast_path enabled (deadlock) and blocking stage without a gate signal."""
    adv_code_blocking_security = {
        "version": 2, "profile": "custom",
        "platform": {"type": "github", "default_branch": "main", "auth": {"token_secret": "REMEDIATION_TOKEN"}},
        "defaults": {"provider": "openai", "models": {}},
        "modules": {"auto_merge": True},
        "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                    "gate": "advisory", "triggers": ["pr_opened", "pr_updated"]},
                   {"id": "security", "type": "security", "backend": {"name": "codex"},
                    "gate": "blocking", "triggers": ["pr_opened", "pr_updated"]}],
    }
    expect_raises(lambda: render.render_all(adv_code_blocking_security, "github"),
                  "auto-merge: blocking security + fast_path enabled fails loud (delta #1, render)")
    expect_raises(lambda: render.validate_config(adv_code_blocking_security),
                  "auto-merge: blocking security + fast_path enabled fails loud (delta #1, front door)")

    blocking_test_stage = {
        "version": 2, "profile": "custom",
        "platform": {"type": "github", "default_branch": "main", "auth": {"token_secret": "REMEDIATION_TOKEN"}},
        "defaults": {"provider": "openai", "models": {}},
        "modules": {"auto_merge": True},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                    "gate": "blocking", "triggers": ["pr_opened", "pr_updated"]},
                   {"id": "test", "type": "test", "gate": "blocking"}],
    }
    expect_raises(lambda: render.render_all(blocking_test_stage, "github"),
                  "auto-merge: blocking stage with no rendered gate signal fails loud (delta #7, render)")
    expect_raises(lambda: render.validate_config(blocking_test_stage),
                  "auto-merge: blocking stage with no rendered gate signal fails loud (delta #7, front door)")


def _check_manual_trigger_and_empty_label_guards(advisory_config: dict) -> None:
    """Blocking review with only a manual trigger and an empty human-merge label are both rejected."""
    manual_review_config = {
        "version": 2, "profile": "custom",
        "platform": {"type": "github", "default_branch": "main", "auth": {"token_secret": "REMEDIATION_TOKEN"}},
        "defaults": {"provider": "openai", "models": {}},
        "modules": {"auto_merge": True},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                    "gate": "blocking", "triggers": ["manual"]}],
    }
    expect_raises(lambda: render.render_all(manual_review_config, "github"),
                  "auto-merge: blocking review with no PR-review trigger fails loud (delta2 #7, render)")
    expect_raises(lambda: render.validate_config(manual_review_config),
                  "auto-merge: blocking review with no PR-review trigger fails loud (delta2 #7, front door)")

    empty_label_config = {**advisory_config,
                          "platform": {"type": "github", "default_branch": "main",
                                       "auth": {"token_secret": "REMEDIATION_TOKEN"},
                                       "labels": {"human_merge": ""}}}
    expect_raises(lambda: render.render_all(empty_label_config, "github"),
                  "auto-merge: empty human_merge label fails loud (delta2, render)")
    expect_raises(lambda: render.validate_config(empty_label_config),
                  "auto-merge: empty human_merge label fails loud (delta2, schema)")


def _check_auto_merge_config_validity_guards(advisory_config: dict) -> None:
    """Required-check names, merge methods, labels, and blocking-stage guards."""
    _check_required_check_and_merge_method_guards(advisory_config)
    _check_blocking_security_and_unsupported_stage_guards()
    _check_manual_trigger_and_empty_label_guards(advisory_config)


def _check_auto_merge_coherence_matrix() -> None:
    """Trigger × gate × lane coherence matrix: every row is accepted or rejected as expected."""
    O, U, OU = ["pr_opened"], ["pr_updated"], ["pr_opened", "pr_updated"]

    def _make_matrix_config(code_gate, code_trig, sec_gate, sec_trig):
        return {"version": 2, "profile": "custom",
                "platform": {"type": "github", "default_branch": "main",
                             "auth": {"token_secret": "REMEDIATION_TOKEN"}},
                "defaults": {"provider": "openai", "models": {}},
                "modules": {"auto_merge": True},
                "routing": {"fast_path": {"enabled": False}},
                "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                            "gate": code_gate, "triggers": code_trig},
                           {"id": "security", "type": "security", "backend": {"name": "codex"},
                            "gate": sec_gate, "triggers": sec_trig}]}

    matrix_rows = [
        ("advisory", OU, "blocking", OU, None),
        ("blocking", OU, "blocking", OU, None),
        ("advisory", O,  "advisory", O,  None),
        ("blocking", OU, "advisory", OU, None),
        ("blocking", U,  "blocking", U,  None),
        ("advisory", O,  "blocking", O,  "b-security"),
        ("blocking", O,  "blocking", O,  "b-review"),
        ("blocking", OU, "blocking", O,  "graph"),
    ]
    for code_gate, code_trig, sec_gate, sec_trig, expect in matrix_rows:
        matrix_config = _make_matrix_config(code_gate, code_trig, sec_gate, sec_trig)
        label = f"matrix[code={code_gate}/{code_trig},sec={sec_gate}/{sec_trig}]"
        if expect is None:
            am_m = render.render_all(matrix_config, "github")["auto-merge.yml"]
            want_code = "true" if code_gate == "blocking" else "false"
            want_sec = "true" if sec_gate == "blocking" else "false"
            check(f'REQUIRE_CODEX_CODE_REVIEW: "{want_code}"' in am_m
                  and f'REQUIRE_CODEX_SECURITY_REVIEW: "{want_sec}"' in am_m,
                  f"auto-merge {label}: renders, REQUIRE code={want_code} sec={want_sec}")
        else:
            expect_raises(lambda c=matrix_config: render.render_all(c, "github"),
                          f"auto-merge {label}: rejected ({expect}) at render")
            expect_raises(lambda c=matrix_config: render.validate_config(c),
                          f"auto-merge {label}: rejected ({expect}) at front door")


def _check_review_graph_lane_selection() -> None:
    """Review-only and code-only graphs emit the correct lane subsets."""
    review_only = {"version": 2, "profile": "custom",
                   "platform": {"type": "github", "default_branch": "main"},
                   "defaults": {"provider": "openai", "models": {}},
                   "stages": [{"id": "review", "type": "review", "provider": "openai",
                               "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]}]}
    r3 = render.render_all(review_only, "github")
    check("implementor.yml" not in r3, "select: no implementor.yml without an implement stage")
    check("validate.yml" in r3 and "request-review.yml" in r3,
          "select: core + review lane still emitted for a review-only graph")

    code_only = {"version": 2, "profile": "custom",
                 "platform": {"type": "github", "default_branch": "main"},
                 "defaults": {"provider": "openai", "models": {}},
                 "stages": [{"id": "review", "type": "review", "provider": "openai",
                             "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]}]}
    r_code = render.render_all(code_only, "github")
    check("post_codex '@codex review'" in r_code["request-review.yml"]
          and _SEC_REVIEW_CMD not in r_code["request-review.yml"],
          "request-review: posts only the code review, never security")
    check("final-security-review.yml" not in r_code,
          "select: no security lane without a codex security stage")


def _check_security_lane_selection() -> None:
    """Security-only graph is rejected; pr_opened-only security graph renders the security lane."""
    security_only = {"version": 2, "profile": "custom",
                     "platform": {"type": "github", "default_branch": "main"},
                     "defaults": {"provider": "openai", "models": {}},
                     "stages": [{"id": "security", "type": "security", "provider": "openai",
                                 "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]}]}
    expect_raises(lambda: render.render_all(security_only, "github"),
                  "select: codex security stage without a code-review stage fails loud (render)")
    expect_raises(lambda: render.validate_config(security_only),
                  "validate: codex security stage without a code-review stage fails loud (front door)")

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
    check(render._needs_codex_pat(render.expand_stages(pr_opened_only)),
          "select: PAT is required for a pr_opened-only security graph (doctor must report it)")


def _check_security_trigger_equality_requirement() -> None:
    """Code/security PR triggers must be equal — supersets and subsets are both rejected."""
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


def test_pipeline_selection() -> None:
    """Lane selection: correct workflows are emitted for each config shape."""
    cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    rendered = render.render_all(cfg, "github")

    _check_dogfood_lane_emission(rendered)
    _check_final_security_review_triggers(rendered)

    minimal = {"version": 2, "profile": "custom",
               "platform": {"type": "github", "default_branch": "main"},
               "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "c"}}},
               "stages": [{"id": "implement", "type": "implement",
                           "backend": {"name": "claude-code-action"}}]}
    _check_minimal_config_lane_selection(minimal)
    _check_auto_merge_implement_only_graph(minimal)
    _check_auto_merge_blocking_codex_review_requirements()

    advisory_config = {"version": 2, "profile": "custom",
                       "platform": {"type": "github", "default_branch": "main",
                                    "auth": {"token_secret": "REMEDIATION_TOKEN"}},
                       "defaults": {"provider": "openai", "models": {}},
                       "modules": {"auto_merge": True},
                       "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                                   "gate": "advisory", "triggers": ["pr_opened", "pr_updated"]}]}
    _check_auto_merge_advisory_and_deadlock_guards(advisory_config)
    _check_auto_merge_coherence_matrix()
    _check_review_graph_lane_selection()
    _check_security_lane_selection()
    _check_security_trigger_equality_requirement()

    # security review posted from the dedicated lane, never alongside the code review
    check(_SEC_REVIEW_CMD in rendered["final-security-review.yml"],
          "final-security-review: requests the security review")
    check(_SEC_REVIEW_CMD not in rendered["request-review.yml"],
          "request-review: never requests the security review (moved to the final lane)")

    # lane registry is the single selection seam
    check({lane.name for lane in render.LANES}
          == {"core", "implementor", "codex-code-review", "codex-security-review", "codex-threads",
              "auto-merge"},
          "select: LANES registry drives template selection")
