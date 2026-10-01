# Claude Code — Implementor Contract

@AGENTS.md

This file holds only Claude Code's own working steps. Every rule of this repository — review, merge,
security, Git, coding standards — lives in `AGENTS.md`, imported above. This file names the
`AGENTS.md` section and never restates the rule.

## Role

Claude Code is the implementer described in `AGENTS.md`, "Agent roles". For each authorized task,
Claude owns the implementation, its tests, the commit, the push, the pull request, and the fixes for
accepted review findings.

## Start every implementation

1. Read the task and extract explicit acceptance criteria.
2. Read this file and the imported `AGENTS.md` contract.
3. Inspect `git status`, the branch, and recent history, and work on a task branch (`AGENTS.md`,
   "Git and pull-request rules").
4. Read the smallest authoritative set of files needed (schema, template, docs) before changing them.
5. On a missing, ambiguous or contradictory design decision, stop as set out in `AGENTS.md`,
   "Mandatory stop condition: design ambiguity".

Before editing, check whether the branch or PR already contains equivalent work; resume it rather
than duplicating branches, commits, or PRs.

## Implement and validate

- Make the smallest coherent change that satisfies the acceptance criteria; avoid unrelated churn.
- Add or update tests/checks for changed behavior and plausible regressions.
- Prefer deterministic checks over extra model calls. Common local checks here:
  - `python .github/scripts/validate_config.py` (schema + the dogfood config through the front door + skills)
  - `python .github/scripts/test_core.py` and `python .github/scripts/test_cli.py` (unit tests)
  - `python -m py_compile` on any changed `.py`
- Read the exact failure, fix the root cause, and rerun the narrowest failing check first.
- Allow at most three attempts for the same failing condition, then stop and report evidence.

## Commit and open the pull request

Self-review with `git diff --check`, `git diff --stat`, `git diff`, and `git status`; remove debug
artifacts and unrelated changes. Commit only after self-review and relevant validation pass.

Push the task branch and open one PR as set out in `AGENTS.md`, "Git and pull-request rules". The PR
description states the task and acceptance criteria, what changed and why, checks run with results,
and assumptions or open questions. Then drive the PR to provably ready in its lane (`AGENTS.md`,
"Merge lanes").

## Review findings

Judge each finding against `AGENTS.md`, "Evaluating review findings", and answer it as set out in
`AGENTS.md`, "Review threads". For an accepted finding: fix it, add or adjust checks, rerun
validation, commit, and push.

## Coding standards

All production and test Python code follows `AGENTS.md`, "Coding standards".

## Resume safely

On resume, inspect the branch, commits, PR, check results, and existing review comments before
acting. Reuse durable state; do not duplicate completed steps. Prefer idempotent, guarded commands;
never force-push over concurrent work unless the task requires it and the expected remote SHA is
verified.
