# Overview — what stagr is (and is not)

## One sentence

stagr is a **platform-neutral control plane** that turns one declarative file
(`.agentic/config.yml`) into a **governed development lane** on a repository's own CI/SCM: it
picks up an approved story, drives implement → review → security → tests → gated merge, and
rests the pull request **provably ready, awaiting human approval** — without ever executing an
agent itself.

Its value is **integration, governance, and portability** — never agent capability.

## Bounded scope: the development lane only

stagr owns exactly one span of the SDLC:

> **approved story → implement → code review (fix loop) → security review → unit / integration /
> performance / custom stages → all green, zero open comments → PR merged to the default branch.**

It starts at an **approved story** and ends at a **merged PR**. Nothing before, nothing after.

- **Before** (turning a requirement into an approved, story-broken-down feature) is the
  **Planning toolkit**.
- **After** (deploying a merged change) is the **CD toolkit**.

These are **separate sibling toolkits**, not stages inside stagr. See
[the sibling toolkits](#the-two-sibling-toolkits) below.

## Non-goals (what keeps stagr a tool, not a framework)

stagr inherits the charter non-goals ([`../CHARTER.md`](../CHARTER.md) §5) and adds the scope
boundaries decided for the three-toolkit split:

- ❌ **Not the planner.** Feature intake, intent expansion, story breakdown, and story approval
  belong to the Planning toolkit.
- ❌ **Not the deployer.** Release, deploy, and promotion belong to the CD toolkit.
- ❌ **Not the orchestrator.** Deciding *which* story to start, tracking live progress across
  many PRs, detecting stuck agents, and holding a project "brain" is an external
  orchestrator's job (see [audit-and-provenance.md](audit-and-provenance.md)). stagr governs a
  single PR's lane; it does not schedule or monitor a fleet.
- ❌ **Not an agent runtime.** stagr renders wiring; the agents (Claude, Codex, …) run on the
  platform's runners or a provider's cloud, always on the user's side of the line.
- ❌ **Not a dashboard/service.** stagr is CLI + config + rendered CI; it *emits* events to the
  user's tools rather than hosting a UI.

## The two sibling toolkits

The three toolkits share one contract family and connect **only through GitHub artifacts** — no
toolkit calls another directly.

| Toolkit | Span | Shape | Connects to stagr via |
|---|---|---|---|
| **Planning** | requirement → approved stories | **Service-shaped** (interactive, stateful, brain-driven; not a CI renderer) | Emits **approved story issues** (with dependency metadata) that stagr consumes |
| **stagr** | approved story → merged PR | **Renderer-shaped** (declarative config → native CI) | — |
| **CD** | merged/released → deployed | **Renderer-shaped** (same contract family as stagr) | Consumes stagr's **merge/release events** |

Planning is service-shaped because its work — a UI intake, document ingestion, an
intent-expansion Q&A loop that asks progressively fewer, non-repeating questions, and a project
brain — cannot be expressed as stateless CI steps. stagr and CD are renderer-shaped because
implement/review/test/deploy map naturally onto discrete, event-driven CI stages.

## Scope alignment with older docs

The generic contract in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) can express *any* stage type
(`plan`, `implement`, `security`, `test`, `review`, `docs`, `release`, `custom`). That stays
true — the contract is generic on purpose. What this design **bounds is stagr's product
scope**: stagr ships and owns the **dev-lane** stages and their gate. The `plan`-family and
`release`/deploy stage types remain expressible by the shared contract, but they are
**delivered by the Planning and CD sibling toolkits**, not by stagr's reference lane. Where
`ARCHITECTURE.md` shows a single pipeline spanning `plan … release`, read it as the *contract's*
reach across the toolkit family, not as stagr's own scope.

## Why this shape wins

Every well-funded competitor is racing to **be** the agent, the IDE, or the model. Almost no one
is a **neutral control plane** that governs whatever agents a repo already has, inside the repo's
own CI/SCM, and hands the merge decision to a human. That neutrality is structurally off-limits
to the platform incumbents (each wants lock-in), it needs no model training or hosted runtime to
build, and it is the one position stagr can defend. See [`../LANDSCAPE.md`](../LANDSCAPE.md).
