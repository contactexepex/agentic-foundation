"""Pipeline/lane selection tests (which workflows are emitted for a given config)."""
from __future__ import annotations

import re

from .harness import REPO_ROOT, check, expect_raises, render

# The final security review is requested with this exact slash command; referenced in several
# assertions, so name it once (avoids a duplicated-literal smell and keeps the command in one place).
_SEC_REVIEW_CMD = "@codex security review"


def test_pipeline_selection() -> None:
    # A codex-backed review/security stage -> the review lane is emitted.
    cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    rendered = render.render_all(cfg, "github")
    for name in ("validate.yml", "review-router.yml", "implementor.yml",
                 "request-review.yml", "final-security-review.yml", "resolve-threads.yml",
                 "auto-merge.yml"):
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

    # Regression (#25/#26): the final-security-review lane must (a) never declare the invalid
    # `pull_request_review_thread` webhook event as a trigger — it fails the whole workflow at startup,
    # so the security review never runs — (b) carry a schedule sweep to re-evaluate a head after its
    # last thread resolves (no GitHub event fires for that), (c) serialize globally so concurrent
    # sweep/event runs can't double-post `@codex security review`, and (d) trigger the ONE security
    # review only AFTER the code review is Completed on the head with zero unresolved threads.
    _sec = rendered["final-security-review.yml"]
    _sec_on = _sec.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    # (a) EXACTLY the three supported triggers: no invalid pull_request_review_thread (declaring it
    # fails the whole workflow at startup, so the security review never runs) and no other stray trigger.
    _triggers = set(re.findall(r"^ {2}([a-z_]+):", _sec_on, re.M))
    check(_triggers == {"issue_comment", "check_suite", "schedule"},
          f"select: final-security-review triggers are exactly issue_comment/check_suite/schedule (got {sorted(_triggers)})")
    # (b) global serialization so a scheduled sweep and an event run can't both pass the check-then-post
    # marker and double-post `@codex security review` (#26 race).
    check("group: request-codex-security\n" in _sec and "cancel-in-progress: false" in _sec,
          "select: final-security-review serializes on one global concurrency group (#26 race)")
    # (c) the security review is gated by the EXECUTABLE logic, not descriptive text: the code-review row
    # must be Completed for the head AND unresolved threads must be exactly zero before it is requested.
    check(_SEC_REVIEW_CMD in _sec, "select: final-security-review requests the security review")
    check("grep -qi 'Completed'" in _sec, "select: gate requires the code-review row Completed on the head")
    check('[[ "$unresolved" == "0" ]]' in _sec, "select: gate requires zero unresolved threads before security")

    # No codex review stage -> the review lane is NOT emitted (module-aware, not glob-all).
    minimal = {"version": 2, "profile": "custom",
               "platform": {"type": "github", "default_branch": "main"},
               "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "c"}}},
               "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}]}
    r2 = render.render_all(minimal, "github")
    check("request-review.yml" not in r2 and "resolve-threads.yml" not in r2,
          "select: no review lane without a codex review stage")
    check("validate.yml" in r2, "select: core pipeline still emitted")
    # The auto-merge gate is a MODULE toggle, off by default -> not emitted here.
    check("auto-merge.yml" not in r2, "select: no auto-merge lane when modules.auto_merge is off")

    # modules.auto_merge: true -> the fail-closed auto-merge gate renders. For this implement-only
    # graph the gate must NOT require a Codex code/security review (none is produced), so it cannot
    # deadlock; and with no merge.required_status_checks it requires no external checks.
    auto = {**minimal, "modules": {"auto_merge": True}}
    r_auto = render.render_all(auto, "github")
    am = r_auto.get("auto-merge.yml", "")
    check("auto-merge.yml" in r_auto, "select: auto-merge lane emitted when modules.auto_merge is on")
    check('REQUIRE_CODEX_CODE_REVIEW: "false"' in am
          and 'REQUIRE_CODEX_SECURITY_REVIEW: "false"' in am,
          "auto-merge: implement-only graph does not require a Codex review (no deadlock)")
    check("REQUIRED_STATUS_CHECKS: '[]'" in am,
          "auto-merge: no external checks required without merge.required_status_checks")

    # A blocking codex review+security graph with auto_merge: the gate requires both head-bound reviews.
    # Coherent only with fast_path OFF (a fast-path-approved trivial PR gets no review -> would deadlock),
    # so a review+auto_merge config disables it. merge.required_status_checks render tool-agnostically.
    q = {"version": 2, "profile": "custom",
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
                     "triggers": ["pr_opened", "pr_updated"]}]}
    amq = render.render_all(q, "github")["auto-merge.yml"]
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

    # #5: an ADVISORY codex review/security stage is comment-only, never a merge blocker, so the gate
    # does not require it (and advisory + fast_path is fine).
    adv = {"version": 2, "profile": "custom",
           "platform": {"type": "github", "default_branch": "main", "auth": {"token_secret": "REMEDIATION_TOKEN"}},
           "defaults": {"provider": "openai", "models": {}},
           "modules": {"auto_merge": True},
           "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"}, "gate": "advisory",
                       "triggers": ["pr_opened", "pr_updated"]}]}
    am_adv = render.render_all(adv, "github")["auto-merge.yml"]
    check('REQUIRE_CODEX_CODE_REVIEW: "false"' in am_adv,
          "auto-merge: an advisory codex review is not a merge requirement (#5)")

    # #2: auto_merge + a blocking codex review with the fast path ON would deadlock trivial PRs -> reject.
    fp_on = {**adv, "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                                "gate": "blocking", "triggers": ["pr_opened", "pr_updated"]}]}
    expect_raises(lambda: render.render_all(fp_on, "github"),
                  "auto-merge: blocking review + fast_path enabled fails loud (deadlock) (#2, render)")
    expect_raises(lambda: render.validate_config(fp_on),
                  "auto-merge: blocking review + fast_path enabled fails loud (#2, front door)")

    # #4: auto_merge + a blocking codex review that runs only on pr_opened cannot gate pushed heads -> reject.
    open_only = {**adv, "routing": {"fast_path": {"enabled": False}},
                 "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                             "gate": "blocking", "triggers": ["pr_opened"]}]}
    expect_raises(lambda: render.render_all(open_only, "github"),
                  "auto-merge: blocking pr_opened-only review fails loud (unreviewed pushed heads) (#4, render)")
    expect_raises(lambda: render.validate_config(open_only),
                  "auto-merge: blocking pr_opened-only review fails loud (#4, front door)")

    # #6: an empty required-check name would silently gate nothing -> fail loud (render + schema).
    empty_chk = {**adv, "routing": {"fast_path": {"enabled": False}},
                 "merge": {"required_status_checks": [{"name": "", "app_id": 1}]}}
    expect_raises(lambda: render.render_all(empty_chk, "github"),
                  "auto-merge: empty required-check name fails loud (#6, render)")
    expect_raises(lambda: render.validate_config(empty_chk),
                  "auto-merge: empty required-check name fails loud (#6, schema)")
    # Feasibility filter: a required check with no app_id / a non-positive app_id is schema-impossible
    # (positive identity is mandatory) — assert the schema rejects it rather than handling it at runtime.
    expect_raises(lambda: render.validate_config({**adv, "routing": {"fast_path": {"enabled": False}},
                  "merge": {"required_status_checks": [{"name": "X"}]}}),
                  "auto-merge: required check without app_id fails loud (schema)")
    expect_raises(lambda: render.validate_config({**adv, "routing": {"fast_path": {"enabled": False}},
                  "merge": {"required_status_checks": [{"name": "X", "app_id": 0}]}}),
                  "auto-merge: required check app_id < 1 fails loud (schema)")
    # A ${{ }} expression in a check name would be evaluated in the env value -> fail loud (render + schema-safe).
    expect_raises(lambda: render.render_all({**adv, "routing": {"fast_path": {"enabled": False}},
                  "merge": {"required_status_checks": [{"name": "${{ github.token }}", "app_id": 1}]}}, "github"),
                  "auto-merge: ${{ }} in a required-check name fails loud (render)")
    # #9: an unknown merge method fails loud (render + schema).
    bad_method = {**adv, "merge": {"method": "fast-forward"}}
    expect_raises(lambda: render.render_all(bad_method, "github"),
                  "auto-merge: unknown merge.method fails loud (#9, render)")
    expect_raises(lambda: render.validate_config(bad_method),
                  "auto-merge: unknown merge.method fails loud (#9, schema)")
    # #7: a human_merge label with a double quote would break the workflow YAML -> fail loud.
    bad_label = {**adv, "platform": {"type": "github", "default_branch": "main",
                                     "auth": {"token_secret": "REMEDIATION_TOKEN"},
                                     "labels": {"human_merge": 'ho"ld'}}}
    expect_raises(lambda: render.render_all(bad_label, "github"),
                  "auto-merge: unsafe human_merge label fails loud (#7-label)")

    # Codex delta review remediation:
    # A blocking security stage (even with an advisory code review) requires fast_path off, else a
    # fast-path-approved trivial PR could never get the security review -> reject.
    adv_code_block_sec = {"version": 2, "profile": "custom",
                          "platform": {"type": "github", "default_branch": "main",
                                       "auth": {"token_secret": "REMEDIATION_TOKEN"}},
                          "defaults": {"provider": "openai", "models": {}},
                          "modules": {"auto_merge": True},
                          "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                                      "gate": "advisory", "triggers": ["pr_opened", "pr_updated"]},
                                     {"id": "security", "type": "security", "backend": {"name": "codex"},
                                      "gate": "blocking", "triggers": ["pr_opened", "pr_updated"]}]}
    expect_raises(lambda: render.render_all(adv_code_block_sec, "github"),
                  "auto-merge: blocking security + fast_path enabled fails loud (delta #1, render)")
    expect_raises(lambda: render.validate_config(adv_code_block_sec),
                  "auto-merge: blocking security + fast_path enabled fails loud (delta #1, front door)")

    # A blocking stage the gate can't enforce (a rendered-nowhere `test` stage) must reject auto_merge,
    # not silently drop that declared blocking gate.
    block_test = {"version": 2, "profile": "custom",
                  "platform": {"type": "github", "default_branch": "main",
                               "auth": {"token_secret": "REMEDIATION_TOKEN"}},
                  "defaults": {"provider": "openai", "models": {}},
                  "modules": {"auto_merge": True},
                  "routing": {"fast_path": {"enabled": False}},
                  "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                              "gate": "blocking", "triggers": ["pr_opened", "pr_updated"]},
                             {"id": "test", "type": "test", "gate": "blocking"}]}
    expect_raises(lambda: render.render_all(block_test, "github"),
                  "auto-merge: blocking stage with no rendered gate signal fails loud (delta #7, render)")
    expect_raises(lambda: render.validate_config(block_test),
                  "auto-merge: blocking stage with no rendered gate signal fails loud (delta #7, front door)")

    # The generic every-check sweep is fail-CLOSED on cancelled/stale unless a same-named success exists
    # (a superseded run replaced by a green one), and external gates require a non-Actions check-run.
    check('per_page=100" --slurp' in amq and "map(.statuses)" in amq,
          "auto-merge: combined status is paginated before context lookup")
    check('-f "base=$DEFAULT_BRANCH"' in amq,
          "auto-merge: default branch passed as an encoded GET param")

    # Second delta pass:
    # A blocking Codex review stage that does NOT take part in PR review (e.g. triggers: [manual]) renders
    # no PR-review lane, so the gate could never verify it -> reject.
    manual_review = {"version": 2, "profile": "custom",
                     "platform": {"type": "github", "default_branch": "main",
                                  "auth": {"token_secret": "REMEDIATION_TOKEN"}},
                     "defaults": {"provider": "openai", "models": {}},
                     "modules": {"auto_merge": True},
                     "routing": {"fast_path": {"enabled": False}},
                     "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"},
                                 "gate": "blocking", "triggers": ["manual"]}]}
    expect_raises(lambda: render.render_all(manual_review, "github"),
                  "auto-merge: blocking review with no PR-review trigger fails loud (delta2 #7, render)")
    expect_raises(lambda: render.validate_config(manual_review),
                  "auto-merge: blocking review with no PR-review trigger fails loud (delta2 #7, front door)")

    # An empty human_merge label leaves nothing that can pause a PR -> reject (render + schema).
    empty_label = {**adv, "platform": {"type": "github", "default_branch": "main",
                                       "auth": {"token_secret": "REMEDIATION_TOKEN"},
                                       "labels": {"human_merge": ""}}}
    expect_raises(lambda: render.render_all(empty_label, "github"),
                  "auto-merge: empty human_merge label fails loud (delta2, render)")
    expect_raises(lambda: render.validate_config(empty_label),
                  "auto-merge: empty human_merge label fails loud (delta2, schema)")

    # --- Auto-merge coherence matrix (trigger x gate x lane) -------------------------------------
    # One deliberate pass closing the class of gaps found piecemeal (delta #1/#4/#7, delta2 #7, and the
    # blocking-security deadlock below). auto_merge ON, fast_path OFF; a codex 'review' + codex 'security'
    # stage with varying gate/triggers. Each row is hand-verified against the rule:
    #   * supported-graph: a security stage taking part in PR review needs a code-review stage with the
    #     SAME PR triggers.
    #   * (a) every BLOCKING stage must be a codex review/security taking part in PR review.
    #   * (b) a BLOCKING review/security stage must run on pushed heads (pr_updated) — else the head
    #     auto-merge merges can never carry the head-bound review the gate requires.
    #   * REQUIRE_CODEX_{CODE,SECURITY}_REVIEW is "true" iff that stage is blocking (it then also runs on
    #     pushed heads, or the row is rejected).
    O, U, OU = ["pr_opened"], ["pr_updated"], ["pr_opened", "pr_updated"]

    def _mk(code_gate, code_trig, sec_gate, sec_trig):
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

    # (code_gate, code_trig, sec_gate, sec_trig, expect): expect is None to PASS (renders), else a short
    # tag for the reason it must be rejected.
    _matrix = [
        ("advisory", OU, "blocking", OU, None),   # sec blocking on push, code advisory on push -> OK
        ("blocking", OU, "blocking", OU, None),   # both blocking on push -> OK
        ("advisory", O,  "advisory", O,  None),   # both advisory: gate needs no codex review -> OK
        ("blocking", OU, "advisory", OU, None),   # code blocking on push, sec advisory -> OK
        ("blocking", U,  "blocking", U,  None),   # pr_updated-only on both is still pushed-head cover -> OK
        # Finding 1 (this review): advisory code + blocking security, both pr_opened-only. Triggers are
        # equal (passes supported-graph) but the blocking security can never be head-bound on a pushed
        # head -> (b) security must reject.
        ("advisory", O,  "blocking", O,  "b-security"),
        # blocking code pr_opened-only -> (b) review rejects first (delta #4).
        ("blocking", O,  "blocking", O,  "b-review"),
        # mismatched triggers: security narrower than code -> supported-graph rejects.
        ("blocking", OU, "blocking", O,  "graph"),
    ]
    for code_gate, code_trig, sec_gate, sec_trig, expect in _matrix:
        cfg_m = _mk(code_gate, code_trig, sec_gate, sec_trig)
        label = f"matrix[code={code_gate}/{code_trig},sec={sec_gate}/{sec_trig}]"
        if expect is None:
            am_m = render.render_all(cfg_m, "github")["auto-merge.yml"]
            want_code = "true" if code_gate == "blocking" else "false"
            want_sec = "true" if sec_gate == "blocking" else "false"
            check(f'REQUIRE_CODEX_CODE_REVIEW: "{want_code}"' in am_m
                  and f'REQUIRE_CODEX_SECURITY_REVIEW: "{want_sec}"' in am_m,
                  f"auto-merge {label}: renders, REQUIRE code={want_code} sec={want_sec}")
        else:
            expect_raises(lambda c=cfg_m: render.render_all(c, "github"),
                          f"auto-merge {label}: rejected ({expect}) at render")
            expect_raises(lambda c=cfg_m: render.validate_config(c),
                          f"auto-merge {label}: rejected ({expect}) at front door")

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
          and _SEC_REVIEW_CMD not in r_code["request-review.yml"],
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
    check(_SEC_REVIEW_CMD in rendered["final-security-review.yml"],
          "final-security-review: requests the security review")
    check(_SEC_REVIEW_CMD not in rendered["request-review.yml"],
          "request-review: never requests the security review (moved to the final lane)")

    # The lane registry is the single selection seam.
    check({lane.name for lane in render.LANES}
          == {"core", "implementor", "codex-code-review", "codex-security-review", "codex-threads",
              "auto-merge"},
          "select: LANES registry drives template selection")
