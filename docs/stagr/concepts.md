# Concepts & vocabulary

This is the shared vocabulary for the rest of the set. For the full layered model (contract →
provider adapters → backends → platform renderers → CLI) see
[`../ARCHITECTURE.md`](../ARCHITECTURE.md); this page defines only the terms the dev-lane design
leans on, plus the one genuinely new concept — the **agent-backend seam**.

## Stage

A **stage** is one unit of the dev lane, bound to:

- a **type** — one of the contract's accepted values **[shipped]**: `review`, `security`,
  `build`, `test`, `deploy`, `custom`. The dev lane uses `review`, `security`, `build`, `test`, and
  `custom`; implementing a story belongs to the future development module (decision record #265). There is **no
  `code-review`/`security-review`/`integration-test`/`performance-test` type**: the friendly name is
  the stage **`id`** (e.g. an `id: code-review` stage of `type: review`, an `id: security-review`
  stage of `type: security`), and integration or performance testing is a `test` or `custom` stage.
  This doc uses the `id`-style names in prose; the `type` is always one of the values above.
- a **provider + model** (the knob; resolved most-specific-first — see `ARCHITECTURE.md` §4),
- a **backend** (the executor; see the seam below),
- one or more **triggers** **[shipped]**: `pr_opened`, `pr_updated`, `issue_labeled`, `manual`,
- a **gate** (see below),
- **dependencies** (`depends_on`) that define the graph edges and therefore the order.

Stages are the only extensibility point: a new capability is a new stage of an existing type, or
a `custom` stage — never a fork of the renderer.

## Trigger + gate = the whole stage contract

Every stage is fully described by *when it runs* (trigger) and *what its result blocks* (gate).
This keeps one generic abstraction for all stage kinds:

- **Trigger** — the event that starts the stage. A PR-centric stage triggers on
  `pull_request` events; a story-centric stage triggers on an issue label.
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

`backend` is a plain string **[shipped]**. Omit it and the provider picks the backend
(`openai` → `codex`). Validation (V-S07) rejects a backend that
has no registered backend renderer.

| Backend | Wraps | Harness kind | Status |
|---|---|---|---|
| `codex` | OpenAI Codex | GitHub-native (Actions + Codex app) | **[shipped]** — code review, security review |
| `openhands`, `pr-agent`, `swe-agent`, provider-agnostic runners | OSS agents / any action | varies | **not available [target]** — no backend renderer yet |
| `claude-code-cli` | Claude Code CLI-in-runner adapter | CLI-in-runner | **not available [Phase 3 target]** |

The **seam pattern** exists now (a stage names a backend; the `provider→backend` default is in the
core). Adding a cloud/CLI backend later is **one new backend renderer registered in the core — never
a renderer rewrite** (this is the "a new backend is a renderer, never a rewrite" charter principle).
The seam also carries a hard invariant **[target]**: a backend should always run on the user's side
of the line — in their CI runner, or by dispatching to a provider's cloud — never inside a
stagr-hosted process.

> The demo binds the reviews→`codex`. That is the
> **default reference binding, not an identity**: stagr is not Codex or Claude; it is the seam
> they plug into.

## Merge lanes

A merged PR reaches the default branch through exactly one of two lanes:

- **Human lane (default).** The gate makes the PR *ready*; a human performs the merge. This is
  the default for every repo.
- **Foundation / auto-merge lane [target].** A fail-closed gate merges automatically once
  the PR is provably ready. Stagr does not provide it today; this repository's own hand-written
  workflow (`auto-merge-foundation-prs.yml`) does it for this repository only. A `human-merge` label
  is always a hard stop, even with auto-merge on.

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
