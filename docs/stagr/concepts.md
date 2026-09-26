# Concepts & vocabulary

This is the shared vocabulary for the rest of the set. For the full layered model (contract →
provider adapters → backends → platform renderers → CLI) see
[`../ARCHITECTURE.md`](../ARCHITECTURE.md); this page defines only the terms the dev-lane design
leans on, plus the one genuinely new concept — the **agent-backend seam**.

## Stage

A **stage** is one unit of the dev lane, bound to:

- a **type** (`implement`, `code-review`, `security-review`, `test`, `integration-test`,
  `performance-test`, `custom`),
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
  - **advisory** — posts a comment only; never blocks.
  - **blocking** — emits a **required status check**; the merge is impossible until it is a clean
    success. Fail-closed: missing / pending / errored ⇒ blocked (see
    [trust-and-correctness.md](trust-and-correctness.md)).

## Backend and the agent-backend seam

A **backend** is the executor that actually runs a stage's agent. stagr derives it from the
provider and lets a stage pin or swap it **by name** — the *agent-backend seam*.

| Backend | Wraps | Harness kind | Ships today |
|---|---|---|---|
| `claude-code-action` | Anthropic Claude Code | GitHub-native (Actions) | ✅ implement |
| `codex` | OpenAI Codex | GitHub-native (Actions + Codex app) | ✅ code review, security review |
| `*-cloud` (e.g. cloud agent APIs) | provider cloud agents | Cloud-API (dispatch + poll) | roadmap |
| `*-cli` | a CLI on the runner | CLI-in-runner | roadmap |

The seam exists in the contract **now**; only the two GitHub-native backends are implemented.
Adding a cloud or CLI backend later is a **new adapter template, not a contract change or a
renderer rewrite** — the "a new backend is a renderer, never a rewrite" charter principle. The
seam also carries a hard invariant: **the backend always runs on the user's side of the line** —
in their CI runner, or by dispatching to a provider's cloud — never inside a stagr-hosted
process. See [security-and-secrets.md](security-and-secrets.md).

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
