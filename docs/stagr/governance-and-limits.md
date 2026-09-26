# Governance & limits — budgets, loops, escalation, merge lanes

The gate says *whether* a PR may merge. This page covers *how much work stagr may spend getting
there*, *what happens when it cannot get there*, and *who performs the merge*. These are rendered
guarantees in the pipeline — not advice an agent may choose to follow.

## Budgets & cost governance

Agents re-review on every push and fix in a loop; unbounded, that burns tokens and money
(providers are increasingly usage-billed). The contract carries a `budgets` block **[shipped]**, but
it is **`enabled: false` by default** — so today an unconfigured repo has **no enforced cap**. The
enforcement below is **[target]** ([roadmap.md](roadmap.md)):

- **Per-PR review-iteration cap** **[target]** — a maximum number of review→fix cycles per PR.
- **Cost ceiling** **[target]** — an optional per-PR (and per-stage) budget; exceeding it stops the
  loop and escalates rather than spending further.
- **Circuit breaker** **[target]** — repeated identical failures, or a stage that never returns,
  trip the breaker instead of retrying forever.

**Target contract:** budgets are honoured by the rendered wiring so a stage cannot silently exceed
its budget, and where a limit is not configured a **safe finite default** applies (never
"unlimited"). **Today:** budgets are opt-in and default-disabled — operators must **not** assume
paid calls are bounded until the finite-default enforcement lands. Closing this is a Phase-1
roadmap item.

## Failure, stuck, and escalation semantics

The happy path is only half the design. Every non-happy outcome has a **defined terminal state**,
and the terminal state is **escalate to a human**, never "loop" and never "silently open."

| Situation | stagr's response |
|---|---|
| Implementer cannot resolve a review finding within the iteration cap | stop the loop, apply `human-merge`, notify — do not keep pushing |
| A review never returns (backend error / no report) | fail-closed (blocked), retry within the cap, then escalate |
| A stage hangs / exceeds its timeout | time out the stage → its blocking check is not-green → gate stays closed → escalate |
| Cost ceiling reached | stop, escalate with the partial state recorded |
| Agents oscillate (fix reintroduces a prior finding) | circuit breaker trips → escalate |
| Genuine design ambiguity surfaced by an agent | stop and ask a human (per `AGENTS.md`); never guess |

**Bounded loops that escalate** is the rule everywhere: a finite number of attempts, then a human.
Escalation is a visible action (label + notification + a decision record — see
[audit-and-provenance.md](audit-and-provenance.md)), never a quiet stall.

## Merge lanes

A ready PR (per [dev-lane.md](dev-lane.md#the-merge-gate--the-definition-of-provably-ready))
reaches the default branch through exactly one lane:

### Human lane — the default

Human approval is **required** to merge. A PR cannot merge without it. This is the default for
every repo and every profile; stagr's job is to make the PR *provably ready* and then stop.

### Auto-merge lane — opt-in module only

A team may enable the `auto_merge` module to let a fail-closed gate merge automatically once the
PR is provably ready — **bypassing human approval by explicit configuration**. Rules:

- **Off by default.** Nothing auto-merges unless a team turns the module on.
- **Configurable controls.** **[shipped]** today the `auto_merge` module exposes the module toggle,
  the **merge method**, **protected paths**, and the **required-checks** set. Richer
  **selectors** (auto-merge only for certain branches / labels / authors / conditions) are
  **[target]** — the contract has no fields for them yet ([roadmap.md](roadmap.md)); do not assume a
  labelled/branch-scoped auto-merge trigger is expressible today.
- **`human-merge` is always a hard stop** — even with auto-merge on, the label blocks the
  automatic merge.
- **Control-plane guard** — a PR that changes a `merge.protected_paths` file (default
  `.github/workflows/**` and `.agentic/**`) is never auto-merged; it is left for a human, so the gate
  and toolkit config cannot be changed by an auto-merged PR.
- **Same fail-closed gate.** Auto-merge uses the identical readiness predicate as the human lane
  (nothing is weakened to enable automation); the merge is SHA-pinned.
- **Never self-merge across principals.** The merge actor is the gate, not the implementer or
  reviewer principal.

### Autonomy window (opt-in, later)

A future extension of the auto-merge lane lets a team grant time-boxed autonomy (e.g. "auto for N
hours") with the same fail-closed gate and a full decision record. It is opt-in, off by default,
and always subordinate to the `human-merge` hard stop. Tracked in [roadmap.md](roadmap.md).

## Relationship to the orchestrator

Budgets, escalation, and lanes here govern **one PR's lane**. Cross-PR concerns — which story to
start, how many run in parallel, an org-wide autonomy window, fleet-level stuck detection — belong
to the external orchestrator, which acts on the events stagr emits. stagr enforces the limits
*within* a lane; it does not schedule *across* lanes.
