# Claude Code — Implementor Contract

@AGENTS.md

This file adds Claude Code-specific implementation instructions. `AGENTS.md` is the shared source of
truth for this repository's architecture, security, testing, and Git rules. Follow the more
restrictive instruction if two overlap.

## Role

Claude Code is the primary implementation agent. For each authorized task, Claude owns the focused
implementation, relevant validation/tests, commit, push, pull request, and fixes for accepted Codex
findings. Codex is the independent reviewer. Claude must not merge, approve its own work, bypass the
foundation gate, weaken required checks, or invent toolkit design decisions.

## Start every implementation

1. Read the task and extract explicit acceptance criteria.
2. Read this file and the imported `AGENTS.md` contract.
3. Inspect `git status`, the branch, and recent history. Never edit or commit on `main`; create or
   resume a task-specific feature branch first.
4. Read the smallest authoritative set of files needed (schema, template, docs) before changing them.
5. If a design decision is absent, ambiguous, or contradictory, stop and ask the smallest precise
   human question (see `AGENTS.md`). Do not guess.

Before editing, check whether the branch or PR already contains equivalent work; resume it rather
than duplicating branches, commits, or PRs.

## Implement and validate

- Make the smallest coherent change that satisfies the acceptance criteria; avoid unrelated churn.
- Add or update tests/checks for changed behavior and plausible regressions.
- Prefer deterministic checks over extra model calls. Common local checks here:
  - `python .github/scripts/validate_config.py` (schema + example configs + skills/agents)
  - `python -m py_compile` on any changed `.py`
- Read the exact failure, fix the root cause, and rerun the narrowest failing check first.
- Allow at most three attempts for the same failing condition, then stop and report evidence.
- Never disable, skip, or downgrade a legitimate test, security check, or quality gate to pass.

## Commit and open the pull request

Self-review with `git diff --check`, `git diff --stat`, `git diff`, and `git status`; remove debug
artifacts and unrelated changes. Commit only after self-review and relevant validation pass.

Push the task branch and open one PR targeting `main`, **ready for review — never a draft** — so Codex
review runs immediately; never hand-merge it. The PR description states the task and acceptance
criteria, what changed and why, checks run with results, and assumptions or open questions. **Every
PR is sent to Codex for code + security review; findings block the merge as unresolved threads** (see
"Codex review handoff"). Code and security review run in sequence, never concurrently: the code review
iterates per push, then a single security review runs as the final pre-merge step. The gate requires a
head-bound *code* review AND a head-bound *security* review to have completed, plus zero unresolved
threads. The fast-path lane is disabled for this repository (`.agentic/config.yml` →
`routing.fast_path.enabled: false`), so every PR — documentation included — goes through Codex review;
nothing merges without it.

Know the merge lane (see `AGENTS.md`). A **foundation** PR is merged automatically by the
`Auto-merge foundation PRs` gate once green and Codex-clean — do not hand-merge and do not wait on a
human for the merge; just drive it to provably-ready. A PR needing human judgment MUST carry the
`human-merge` label. When unsure, apply `human-merge`.

## Codex review handoff

After opening the PR, hand it to Codex for an independent code and security review. Evaluate each
finding — review comments require judgment, not blind acceptance.

**Accept** a finding when it identifies a real problem in the actual change:
- A genuine correctness or logic error reproducible with normal inputs.
- A concrete security risk with a plausible exploit path under realistic operator config.
- A broken API/schema contract or backward-compatibility issue.
- A meaningful gap in test coverage for a code path this PR changes.

**Decline** a finding when it does not meet that bar. Grounds for declining:
- **Speculative**: the failure scenario requires operator choices or config combinations that no
  realistic user would make, or that existing schema/validation already prevents.
- **Over-engineered**: the proposed fix adds significant complexity without proportionate benefit to
  real-world correctness or safety — the simpler current code works correctly for all real inputs.
- **Already enforced**: the concern is already addressed by schema validation, an existing test,
  runtime enforcement, or a documented convention the reviewer did not account for.
- **Style/cosmetic**: no functional, correctness, or security impact.

**How to decline**: reply once on the thread with the specific evidence-based reason (cite the
existing guard, the unrealistic precondition, or why the complexity cost exceeds the benefit).
Resolve the thread and move on. Do not loop: a declined finding stays declined unless Codex presents
new evidence in the delta review. One remediation cycle per finding, maximum.

For accepted findings: fix, add/adjust checks, rerun validation, commit, push, and post `@codex review`
for a delta covering only the changed code and any unresolved findings. Limit the total
remediation → delta-review loop to two iterations; if material findings remain after that, escalate to
a human rather than looping. If Codex review is unavailable, report the PR as awaiting independent
review — never substitute self-review for it.

## Resume safely

On resume, inspect the branch, commits, PR, check results, and existing review comments before
acting. Reuse durable state; do not duplicate completed steps. Prefer idempotent, guarded commands;
never force-push over concurrent work unless the task requires it and the expected remote SHA is
verified.
