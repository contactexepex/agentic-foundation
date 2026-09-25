"""Behavioral tests for the rendered auto-merge gate SHELL logic (Codex plan review: behavioral, not
just static). The gate's `gates_pass`/`evaluate_pr` functions are extracted from the rendered
auto-merge.yml, sourced in bash with a STUBBED `gh` that returns fixture JSON, and driven through
scenarios asserting the merge/skip decision. This exercises the real jq/shell: SHA binding, actor +
completion markers, (app.id,name) identity, latest-attempt-by-id rerun policy, pagination shape,
fail-closed on API error, the human-merge hard stop, the control-plane guard, and the self-check defer.

Requires `bash` and `jq` (present on the CI runner and in this dev image). If jq is missing the module
skips loudly rather than passing silently.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap

from .harness import check, render

HEAD = "a" * 40
OTHER = "b" * 40
CODEX = "chatgpt-codex-connector[bot]"


def _gate_functions() -> str:
    """Extract the function definitions (skip … through evaluate_pr) from the rendered gate, dedented."""
    cfg = {
        "version": 2, "profile": "custom",
        "platform": {"type": "github", "default_branch": "main", "auth": {"token_secret": "REMEDIATION_TOKEN"}},
        "defaults": {"provider": "openai", "models": {}},
        "modules": {"auto_merge": True},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [
            {"id": "review", "type": "review", "backend": {"name": "codex"}, "gate": "blocking",
             "triggers": ["pr_opened", "pr_updated"]},
            {"id": "security", "type": "security", "backend": {"name": "codex"}, "gate": "blocking",
             "triggers": ["pr_opened", "pr_updated"]},
        ],
    }
    am = render.render_all(cfg, "github")["auto-merge.yml"]
    # The run block is the last content in the file; split on `run: |` and dedent (it contains blank lines,
    # so a per-line indented-block regex would stop early).
    run = textwrap.dedent(am.split("run: |\n", 1)[1])
    start = run.index("skip() {")
    end = run.index("for pr in ")
    return run[start:end]


def _summary_comment(code_completed_sha: str | None, sec_head: str | None, sec_status: str = "completed") -> str:
    """A Codex summary comment body: optional visible 'Code Review Completed `<sha>`' row, and the hidden
    security marker with a full headSha + status (the authoritative security signal)."""
    lines = ["<!-- codex-pull-request-review-summary -->", "## Codex Review Summary", ""]
    if code_completed_sha:
        lines.append(f"| Code Review | Completed | `{code_completed_sha}` |")
    if sec_head:
        lines.append(
            '<!-- codex-security-review:v1 {"blockingSeverityThreshold":"P0",'
            f'"headSha":"{sec_head}","status":"{sec_status}"}} -->'
        )
        lines.append(f"| Security Review | {'Completed' if sec_status=='completed' else 'Running'} | `{sec_head[:7]}` |")
    return "\n".join(lines)


def _defaults() -> dict:
    """Fully-green fixture set (happy path → merge)."""
    pr = {"state": "open", "merged": False, "draft": False,
          "head": {"sha": HEAD, "repo": {"full_name": "o/r"}},
          "base": {"ref": "main"}, "author_association": "OWNER",
          "mergeable": True, "mergeable_state": "clean", "labels": []}
    checks = [{"check_runs": [
        {"id": 1, "name": "Validate", "app": {"id": 15368, "slug": "github-actions"},
         "status": "completed", "conclusion": "success"},
    ]}]
    status = [{"state": "success", "statuses": [
        {"context": "Publish fast review result", "state": "success", "updated_at": "2020-01-01"}]}]
    reviews = [[{"id": 10, "user": {"login": CODEX, "id": 999}, "commit_id": HEAD,
                 "state": "COMMENTED", "body": "### 💡 Codex Review\nsuggestions", "submitted_at": "2020"}]]
    comments = [[{"user": {"login": CODEX, "id": 999}, "body": _summary_comment(HEAD, HEAD)}]]
    threads = {"data": {"repository": {"pullRequest": {"reviewThreads": {
        "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
    return {
        "PR_JSON": json.dumps(pr), "FILES_JSON": json.dumps([[{"filename": "src/app.py"}]]),
        "STATUS_JSON": json.dumps(status), "CHECKS_JSON": json.dumps(checks),
        "REVIEWS_JSON": json.dumps(reviews), "COMMENTS_JSON": json.dumps(comments),
        "THREADS_JSON": json.dumps(threads), "VALIDATE_RUN_OK": "1",
        "REQUIRED_STATUS_CHECKS": "[]", "REQUIRE_CODEX_CODE_REVIEW": "true",
        "REQUIRE_CODEX_SECURITY_REVIEW": "true", "FAIL_PULL": "0", "FAIL_FILES": "0",
    }


def _run_gate(fixtures: dict) -> str:
    fx = _defaults()
    fx.update(fixtures)
    stub = r"""
set -uo pipefail
export REPO="o/r" DEFAULT_BRANCH="main"
export HUMAN_MERGE_LABEL="human-merge"
export REVIEW_STATUS_CONTEXT="Publish fast review result"
export CODEX_BOT_LOGIN="chatgpt-codex-connector[bot]"
export TRUSTED_ROLES='["OWNER","MEMBER","COLLABORATOR"]'
declare -a PROTECTED=(); mapfile -t PROTECTED < <(jq -r '.[]?' <<<'[".github/workflows/**",".agentic/**"]')

gh() {
  local args="$*"
  if [[ "$args" == *"--method PUT"*"/merge"* ]]; then return 0; fi
  if [[ "$args" == *"actions/workflows/validate.yml/runs"* ]]; then printf '%s' "$VALIDATE_RUN_OK"; return 0; fi
  if [[ "$args" == *graphql* ]]; then printf '%s' "$THREADS_JSON"; return 0; fi
  case "$args" in
    *"/pulls/1/files"*)   [[ "$FAIL_FILES" == 1 ]] && return 1; printf '%s' "$FILES_JSON" ;;
    *"/pulls/1/reviews"*) printf '%s' "$REVIEWS_JSON" ;;
    *"/pulls/1"*)         [[ "$FAIL_PULL" == 1 ]] && return 1; printf '%s' "$PR_JSON" ;;
    *"/commits/"*"/status"*)     printf '%s' "$STATUS_JSON" ;;
    *"/commits/"*"/check-runs"*) printf '%s' "$CHECKS_JSON" ;;
    *"/issues/1/comments"*)      printf '%s' "$COMMENTS_JSON" ;;
    *) printf '{}' ;;
  esac
}
"""
    # Pass fixtures through the process environment, NOT as inline `export VAR=...` lines: a fixture body
    # can contain backticks / quotes / $ (real Codex comment bodies do), which bash would execute or mangle
    # if spliced into the script. env= sets them verbatim.
    script = stub + _gate_functions() + '\nevaluate_pr 1\n'
    env = {**os.environ, **{k: str(v) for k, v in fx.items()}}
    proc = subprocess.run(["bash", "-c", script], text=True, capture_output=True, env=env)
    return proc.stdout + proc.stderr


def _merges(fixtures: dict) -> bool:
    out = _run_gate(fixtures)
    return "Merged #1." in out


def test_gate_behavior() -> None:
    if not (shutil.which("bash") and shutil.which("jq")):
        check(False, "gate-behavior: bash+jq required to run behavioral fixtures")
        return

    # Happy path: every gate green -> merges.
    check(_merges({}), "gate: fully-green PR merges")

    # Eligibility hard stops.
    check(not _merges({"PR_JSON": _defaults()["PR_JSON"].replace('"labels": []', '"labels": [{"name": "human-merge"}]')}),
          "gate: human-merge label blocks (hard stop)")
    def pr(**o):
        base = json.loads(_defaults()["PR_JSON"]); base.update(o); return {"PR_JSON": json.dumps(base)}
    check(not _merges(pr(draft=True)), "gate: draft blocks")
    check(not _merges(pr(state="closed")), "gate: non-open blocks")
    check(not _merges(pr(mergeable_state="behind")), "gate: mergeable_state != clean blocks")
    check(not _merges(pr(author_association="CONTRIBUTOR")), "gate: untrusted author blocks")
    check(not _merges(pr(head={"sha": HEAD, "repo": {"full_name": "fork/r"}})), "gate: fork head blocks")

    # Control-plane guard.
    check(not _merges({"FILES_JSON": json.dumps([[{"filename": ".github/workflows/validate.yml"}]])}),
          "gate: a PR changing a control-plane path is human-gated")
    check(_merges({"FILES_JSON": json.dumps([[{"filename": "docs/x.md"}, {"filename": "src/y.py"}]])}),
          "gate: a PR touching only non-protected paths is not blocked by the guard")
    # A rename that moves a protected file OUT of the protected dir puts the protected path in
    # previous_filename — the guard must check both names.
    check(not _merges({"FILES_JSON": json.dumps([[
        {"filename": "tools/auto-merge.yml", "previous_filename": ".github/workflows/auto-merge.yml"}]])}),
          "gate: a rename of a protected file (previous_filename) is human-gated")

    # CI gates.
    check(not _merges({"STATUS_JSON": json.dumps([{"state": "failure", "statuses": [
        {"context": "Publish fast review result", "state": "success", "updated_at": "2020"}]}])}),
          "gate: combined status != success blocks")
    check(not _merges({"STATUS_JSON": json.dumps([{"state": "success", "statuses": []}])}),
          "gate: missing review-router status blocks")
    check(not _merges({"CHECKS_JSON": json.dumps([{"check_runs": [
        {"id": 1, "name": "Validate", "app": {"id": 15368, "slug": "github-actions"}, "status": "completed", "conclusion": "success"},
        {"id": 2, "name": "CI", "app": {"id": 15368, "slug": "github-actions"}, "status": "completed", "conclusion": "failure"}]}])}),
          "gate: a failed check-run blocks")
    check(not _merges({"CHECKS_JSON": json.dumps([{"check_runs": [
        {"id": 9, "name": "SomeOther", "app": {"id": 1, "slug": "x"}, "status": "completed", "conclusion": "success"}]}])}),
          "gate: missing Validate check blocks (fail-open hole closed)")
    check(not _merges({"VALIDATE_RUN_OK": "0"}),
          "gate: Validate check present but no trusted validate.yml run for head blocks")
    # Self-check defer: the gate's own in-progress run on the head blocks (event-driven defers to the sweep).
    check(not _merges({"CHECKS_JSON": json.dumps([{"check_runs": [
        {"id": 1, "name": "Validate", "app": {"id": 15368, "slug": "github-actions"}, "status": "completed", "conclusion": "success"},
        {"id": 2, "name": "Auto-merge eligible PRs", "app": {"id": 15368, "slug": "github-actions"}, "status": "in_progress", "conclusion": None}]}])}),
          "gate: the gate's own in-progress check defers (no name-based exclusion)")

    # External required checks: positive (app.id, name) identity.
    sonar_ok = [{"check_runs": [
        {"id": 1, "name": "Validate", "app": {"id": 15368, "slug": "github-actions"}, "status": "completed", "conclusion": "success"},
        {"id": 2, "name": "Sonar", "app": {"id": 111, "slug": "sonar"}, "status": "completed", "conclusion": "success"}]}]
    check(_merges({"CHECKS_JSON": json.dumps(sonar_ok), "REQUIRED_STATUS_CHECKS": json.dumps([{"name": "Sonar", "app_id": 111}])}),
          "gate: required external check present with the right app_id passes")
    check(not _merges({"CHECKS_JSON": json.dumps(sonar_ok), "REQUIRED_STATUS_CHECKS": json.dumps([{"name": "Sonar", "app_id": 222}])}),
          "gate: same-name external check from the WRONG app_id does not satisfy (spoof blocked)")
    check(not _merges({"REQUIRED_STATUS_CHECKS": json.dumps([{"name": "Sonar", "app_id": 111}])}),
          "gate: a configured external check that is absent blocks")
    # Rerun policy: latest attempt by id decides — a later cancelled rerun is NOT superseded by an older success.
    check(not _merges({"CHECKS_JSON": json.dumps([{"check_runs": [
        {"id": 1, "name": "Validate", "app": {"id": 15368, "slug": "github-actions"}, "status": "completed", "conclusion": "success"},
        {"id": 5, "name": "Sonar", "app": {"id": 111, "slug": "sonar"}, "status": "completed", "conclusion": "success"},
        {"id": 6, "name": "Sonar", "app": {"id": 111, "slug": "sonar"}, "status": "completed", "conclusion": "cancelled"}]}]),
        "REQUIRED_STATUS_CHECKS": json.dumps([{"name": "Sonar", "app_id": 111}])}),
          "gate: a later cancelled rerun blocks (no fallback to an older success)")

    # Codex code review state machine.
    check(not _merges({"REVIEWS_JSON": json.dumps([[{"id": 10, "user": {"login": CODEX, "id": 999},
        "commit_id": OTHER, "state": "COMMENTED", "body": "### 💡 Codex Review", "submitted_at": "2020"}]]),
        "COMMENTS_JSON": json.dumps([[{"user": {"login": CODEX, "id": 999}, "body": _summary_comment(None, HEAD)}]])}),
          "gate: a Codex code review bound to a different head does not count")
    check(not _merges({"REVIEWS_JSON": json.dumps([[{"id": 10, "user": {"login": CODEX, "id": 999},
        "commit_id": HEAD, "state": "DISMISSED", "body": "### 💡 Codex Review", "submitted_at": "2020"}]])}),
          "gate: a DISMISSED head-bound Codex code review blocks")
    check(not _merges({"REVIEWS_JSON": json.dumps([[{"id": 10, "user": {"login": "someone", "id": 1},
        "commit_id": HEAD, "state": "COMMENTED", "body": "### 💡 Codex Review", "submitted_at": "2020"}]]),
        "COMMENTS_JSON": json.dumps([[{"user": {"login": CODEX, "id": 999}, "body": _summary_comment(None, HEAD)}]])}),
          "gate: a code review by the wrong actor does not count")
    # Clean review (no object) but summary Code Review Completed for head -> passes via documented fallback.
    check(_merges({"REVIEWS_JSON": json.dumps([[]]),
        "COMMENTS_JSON": json.dumps([[{"user": {"login": CODEX, "id": 999}, "body": _summary_comment(HEAD, HEAD)}]])}),
          "gate: a clean code review (summary Completed for head, no object) passes")

    # Codex security review.
    check(not _merges({"COMMENTS_JSON": json.dumps([[{"user": {"login": CODEX, "id": 999},
        "body": _summary_comment(HEAD, OTHER)}]])}),
          "gate: a security review bound to a different head does not count")
    check(not _merges({"COMMENTS_JSON": json.dumps([[{"user": {"login": CODEX, "id": 999},
        "body": _summary_comment(HEAD, HEAD, sec_status="running")}]])}),
          "gate: a security review still running blocks")

    # Reviews / threads.
    check(not _merges({"THREADS_JSON": json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "nodes": [{"isResolved": False}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}})}),
          "gate: an unresolved review thread blocks")
    check(not _merges({"REVIEWS_JSON": json.dumps([[
        {"id": 10, "user": {"login": CODEX, "id": 999}, "commit_id": HEAD, "state": "COMMENTED", "body": "### 💡 Codex Review", "submitted_at": "2020"},
        {"id": 11, "user": {"login": "human", "id": 5}, "commit_id": HEAD, "state": "CHANGES_REQUESTED", "body": "no", "submitted_at": "2021"}]])}),
          "gate: a reviewer's latest CHANGES_REQUESTED blocks")

    # Fail-closed on API error.
    check(not _merges({"FAIL_PULL": "1"}), "gate: an API error fetching the PR fails closed (no merge)")
    check(not _merges({"FAIL_FILES": "1"}), "gate: an API error fetching changed files fails closed")

    # When no codex review is required, the gate does not demand one.
    check(_merges({"REQUIRE_CODEX_CODE_REVIEW": "false", "REQUIRE_CODEX_SECURITY_REVIEW": "false",
                   "REVIEWS_JSON": json.dumps([[]]), "COMMENTS_JSON": json.dumps([[]])}),
          "gate: with no codex review required, a green PR merges without review evidence")
