#!/usr/bin/env python3
"""Standalone test: validate the org-branch-protection ruleset reference template.

Checks that the JSON at docs/stagr/rulesets/org-branch-protection.json:
  - is valid JSON;
  - is an org-level ruleset (target == "branch", enforcement == "active");
  - includes a pull_request rule with dismiss_stale_reviews_on_push == true
    and required_approving_review_count == 0;
  - includes a required_status_checks rule with strict_required_status_checks_policy == true,
    do_not_enforce_on_create == true, and contexts exactly {"Validate", "Publish fast review result"}.

Run with: python .github/scripts/test_rulesets.py
Exit 0 = all checks pass.  Exit 1 = one or more failures (details printed).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RULESET_PATH = Path(__file__).resolve().parents[2] / "docs" / "stagr" / "rulesets" / "org-branch-protection.json"

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def test_ruleset_json() -> None:
    print("test_ruleset_json")

    # 1. File exists and is valid JSON.
    if not RULESET_PATH.exists():
        fail(f"ruleset file not found: {RULESET_PATH}")
        return
    try:
        data = json.loads(RULESET_PATH.read_text())
    except json.JSONDecodeError as exc:
        fail(f"ruleset is not valid JSON: {exc}")
        return
    ok("file exists and is valid JSON")

    # 2. Top-level structure: org ruleset target + active enforcement.
    if data.get("target") == "branch":
        ok("target == 'branch'")
    else:
        fail(f"expected target='branch', got {data.get('target')!r}")

    if data.get("enforcement") == "active":
        ok("enforcement == 'active'")
    else:
        fail(f"expected enforcement='active', got {data.get('enforcement')!r}")

    # 3. Rules list must be present and non-empty.
    rules = data.get("rules")
    if not isinstance(rules, list) or len(rules) == 0:
        fail("'rules' must be a non-empty list")
        return
    ok(f"rules list present with {len(rules)} rule(s)")

    # 4. pull_request rule with dismiss_stale_reviews_on_push == true
    #    and required_approving_review_count == 0.
    pr_rules = [r for r in rules if isinstance(r, dict) and r.get("type") == "pull_request"]
    if not pr_rules:
        fail("no 'pull_request' rule found — branch protection missing")
    else:
        pr_params = pr_rules[0].get("parameters", {})
        if pr_params.get("dismiss_stale_reviews_on_push") is True:
            ok("dismiss_stale_reviews_on_push == true")
        else:
            fail(
                "pull_request rule must have parameters.dismiss_stale_reviews_on_push == true; "
                f"got {pr_params.get('dismiss_stale_reviews_on_push')!r}"
            )
        if pr_params.get("required_approving_review_count") == 0:
            ok("required_approving_review_count == 0")
        else:
            fail(
                "pull_request rule must have parameters.required_approving_review_count == 0 "
                "so the payload is API-valid and foundation-lane auto-merge is not blocked; "
                f"got {pr_params.get('required_approving_review_count')!r}"
            )

    # 5. required_status_checks rule with exactly the required context names
    #    and strict evaluation enabled.
    rsc_rules = [r for r in rules if isinstance(r, dict) and r.get("type") == "required_status_checks"]
    if not rsc_rules:
        fail("no 'required_status_checks' rule found — required checks missing")
    else:
        rsc_params = rsc_rules[0].get("parameters", {})
        if rsc_params.get("strict_required_status_checks_policy") is True:
            ok("strict_required_status_checks_policy == true")
        else:
            fail(
                "required_status_checks rule must have parameters.strict_required_status_checks_policy == true; "
                f"got {rsc_params.get('strict_required_status_checks_policy')!r}"
            )
        if rsc_params.get("do_not_enforce_on_create") is True:
            ok("do_not_enforce_on_create == true")
        else:
            fail(
                "required_status_checks rule must have parameters.do_not_enforce_on_create == true "
                "so newly created repositories can push their initial default branch; "
                f"got {rsc_params.get('do_not_enforce_on_create')!r}"
            )
        check_entries = rsc_params.get("required_status_checks", [])
        if not isinstance(check_entries, list):
            fail(f"required_status_checks must be a list; got {check_entries!r}")
        else:
            contexts = {c.get("context") for c in check_entries if isinstance(c, dict)}
            required_contexts = {"Validate", "Publish fast review result"}
            missing_contexts = required_contexts - contexts
            extra_contexts = contexts - required_contexts
            if missing_contexts or extra_contexts:
                parts = ["required_status_checks must contain exactly the required contexts"]
                if missing_contexts:
                    parts.append(f"missing: {sorted(missing_contexts)}")
                if extra_contexts:
                    parts.append(f"unexpected: {sorted(extra_contexts)}")
                parts.append(f"got: {sorted(contexts)}")
                fail("; ".join(parts))
            else:
                ok(
                    f"required_status_checks contains exactly required contexts: "
                    f"{sorted(required_contexts)}"
                )


def main() -> int:
    print(f"Validating: {RULESET_PATH.relative_to(Path(__file__).resolve().parents[2])}")
    test_ruleset_json()
    if failures:
        print(f"\n{len(failures)} failure(s). See above.")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
