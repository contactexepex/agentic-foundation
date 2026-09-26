# Concepts & vocabulary

This is the shared vocabulary for the rest of the set. For the full layered model (contract →
provider adapters → backends → platform renderers → CLI) see
[`../ARCHITECTURE.md`](../ARCHITECTURE.md); this page defines only the terms the dev-lane design
leans on, plus the one genuinely new concept — the **agent-backend seam**.

## Stage

A **stage** is one unit of the dev lane, bound to:

- a **type** — one of the contract's accepted values **[shipped]**: `plan`, `implement`,
  `security`, `test`, `integration-test`, `review`, `docs`, `release`, `custom`. The dev lane uses
  `implement`, `review`, `security`, `test`, `integration-test`, and `custom`. There is **no
  `code-review`/`security-review`/`performance-test` type**: the friendly name is the stage **`id`**
  (e.g. an `id: code-review` stage of `type: review`, an `id: security-review` stage of
  `type: security`), and performance testing is a `test` or `custom` stage. This doc uses the
  `id`-style names in prose; the `type` is always one of the values above.
- a **provider + model** (the knob; resolved most-specific-first — see `ARCHITECTURE.md` §4),
- a **backend** (the executor; see the seam below),
- one or more **triggers** (issue label, PR opened/updated, comment command, push, schedule,
  manual dispatch),
- a **gate** (see below),
- **dependencies** (`depends_on`) that define the graph edges and therefore the order.

Stages are the only extensibility point: a new capability is a new stage of an existing type, or
a `custom` stage — never a fork of the renderer.

## Trigger + gate = the whole stage contract

Every stage is fully described by *when it runs* (trigger) and *what its result blocks* (gate).
This keeps one generic abstraction for all stage kinds:

- **Trigger** — the event that starts the stage. A PR-centric stage triggers on
  `pull_request` events; a story-centric stage triggers on an issue label; a sweep triggers on
  schedule.
- **Gate** — how the stage's outcome affects the merge:
  - **advisory** — emits **no required status check** of its own, so its outcome never adds a merge
    requirement. It is *not* a guarantee of "cannot affect readiness": an advisory **review** can
    still open review threads, and the zero-open-threads predicate ([dev-lane.md](dev-lane.md)) counts
    review threads **regardless** of the producing stage's gate — so an advisory reviewer's unresolved
    finding still gates the merge until resolved. "Advisory" means "adds no required check," not
    "invisible to the gate."
  - **blocking** — emits a **required status check**; the merge is impossible until it is a clean
    success. Fail-closed: missing / pending / errored ⇒ blocked (see
    [trust-and-correctness.md](trust-and-correctness.md)).

## Backend and the agent-backend seam

A **backend** is the executor that actually runs a stage's agent. stagr derives it from the
provider and lets a stage pin or swap it **by name** — the *agent-backend seam*.

`backend.name` is a **closed enum [shipped]**: `generic`, `claude-code-action`, `openhands`,
`pr-agent`, `codex`, `swe-agent`, `custom`, `claude-code-cli`.

| Backend | Wraps | Harness kind | Status |
|---|---|---|---|
| `claude-code-action` | Anthropic Claude Code | GitHub-native (Actions) | **[shipped]** — implement |
| `codex` | OpenAI Codex | GitHub-native (Actions + Codex app) | **[shipped]** — code review, security review |
| `generic`, `openhands`, `pr-agent`, `swe-agent`, `custom` | provider-agnostic runner / OSS agents / any action | varies | enum-accepted for forward-compat, **not rendered [target]** |
| `claude-code-cli` | Claude Code CLI-in-runner adapter | CLI-in-runner | enum-accepted (follows the `*-cli` pattern, mirrors `claude-code-action`), **not rendered [Phase 3 target]** |

The **seam pattern** exists now (a stage names a backend; the enum + `provider→tool` derivation is
in the schema). But because the enum is **closed**, adding a cloud/CLI backend later is a **new
adapter template *plus* adding its name to the `backend.name` enum — a backward-compatible schema
addition, never a renderer rewrite** (this is the "a new backend is a renderer, never a rewrite"
charter principle, honest about the small schema step it needs). The seam also carries a hard
invariant **[target for the implementer]**: a backend should always run on the user's side of the
line — in their CI runner, or by dispatching to a provider's cloud — never inside a stagr-hosted
process. See [security-and-secrets.md](security-and-secrets.md) for where the shipped implementer
does not yet meet the isolation half of this.

> The demo binds `implement`→`claude-code-action` and the reviews→`codex`. That is the
> **default reference binding, not an identity**: stagr is not Codex or Claude; it is the seam
> they plug into.

## Merge lanes

A merged PR reaches the default branch through exactly one of two lanes:

- **Human lane (default).** The gate makes the PR *ready*; a human performs the merge. This is
  the default for every repo.
- **Foundation / auto-merge lane (opt-in module).** A fail-closed gate merges automatically once
  the PR is provably ready. Off by default; a team enables the `auto_merge` module and configures
  its own rules. A `human-merge` label is always a hard stop, even with auto-merge on.

See [governance-and-limits.md](governance-and-limits.md) for the lane rules and
[trust-and-correctness.md](trust-and-correctness.md) for what "provably ready" means.

## Profile

A **profile** expands to a default dev-lane stage graph so the common repo configures a handful
of lines. Profiles compose with explicit stages (a listed stage merges onto the profile's stage
of the same id). Profile expansions are defined in [dev-lane.md](dev-lane.md#profiles).

## Platform renderer

The contract is written once and **rendered** per platform. `platform.type` selects the renderer;
**GitHub ships first**, others (`gitlab`, `azure_devops`, `bitbucket`) follow as pure renderers.
Neutrality is a design principle enforced by keeping platform specifics in the renderer layer, not
a near-term deliverable — see [roadmap.md](roadmap.md).
