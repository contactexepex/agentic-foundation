# agentic-foundation — architecture

This is the design of the toolkit: the mental model, the layers, and how it stays
**easy for newcomers** yet **granular for experts**, across **any provider/model**,
**any SCM platform**, and **any language**.

> **Scope note.** The contract described here is **generic** — it can express any stage type
> (`implement`, `review`, `security`, `build`, `test`, `custom`). stagr's
> **product scope**, however, is the **development lane** (approved story → merged PR). Planning
> and CD/deploy are delivered by **separate sibling toolkits** that reuse this same contract, not
> by stagr's reference lane. The contract's reach across the toolkit family is wider than
> stagr's own span. The authoritative, refined design and
> roadmap live in [`stagr/`](stagr/README.md) — start with [`stagr/overview.md`](stagr/overview.md).

---

## 1. Mental model: a pipeline is a graph of stages

A repository's agentic pipeline is an **ordered, extensible graph of stages**. Each
**stage is one agent** in the SDLC/STLC — `implement`, `review`, `security`, `build`, `test`,
or `custom` — bound to:

- a **provider + model** (the knob — `anthropic` or `openai` today; mix per stage),
- a **backend** (the executor/tool; derived from the provider, overridable),
- **triggers** (issue label, PR/MR opened or updated, manual),
- a **gate** (advisory = comment only; blocking = emits a required status check),
- **dependencies** (`depends_on`) that define the graph edges.

`implement` and `review` are just two built-in stage *types*; they are not special.
The same contract expresses a two-stage pipeline or a full SDLC of a dozen stages.

```
issue ──▶ [implement] ─┬─▶ [security] ──┐
                     ├─▶ [test]     ──┤─▶ gates ─▶ PR/MR ─▶ human
                     └─▶ [review]   ──┘
```

---

## 2. Layers (separation of concerns)

The toolkit is deliberately split so each concern can change without disturbing the others.

| Layer | Responsibility | Configured by |
|---|---|---|
| **1. Contract** | Declarative, platform-neutral description of the pipeline. | `.agentic/config.yml` (this schema) |
| **2. Provider adapters** | Talk to a model vendor (Claude / OpenAI / Gemini / local / gateway). Give true provider-agnosticism. | `providers`, `defaults.models` |
| **3. Agent tools** | Execute a stage. The tool is derived from the provider (`anthropic` → Claude Code, `openai` → Codex); roadmap adapters wrap other OSS agents. | `stages[].provider` (or `stages[].backend` to pin) |
| **4. Platform/SCM adapters** | Render the neutral pipeline into a concrete CI system and normalize concepts (PR↔MR, roles, checks). | `platform` |
| **5. CLI** | Today: `help`, `plan` (list the files a config produces) and `apply` (write them). Planned: `init`, `doctor`. | — |

The **contract never names a language, a vendor SDK, or a CI system directly** — those
live in layers 2–4, so a repo swaps any of them by editing config, not workflows.

---

## 3. Agent tools — compose, don't reinvent

A landscape scan (see `docs/LANDSCAPE.md`) shows mature OSS agents already do the hard
parts well, but none bundle a configurable implementer **and** reviewer as one
provider-agnostic, drop-in toolkit. So agentic-foundation is an **orchestration /
contract layer**: a stage names a **provider**, and the toolkit derives the coding tool
(the *backend*) and wires it in. Normally a stage sets only `provider`; an explicit
`backend` pins a tool or adopts a roadmap adapter.

| Backend (tool) | Wraps | Derived from | Status |
|---|---|---|---|
| `claude-code-action` | Anthropic's Claude Code | `anthropic` | backend renderer exists; the GitHub renderer cannot render it yet (see below) |
| `codex` | OpenAI Codex | `openai` | rendered on GitHub: review, security |
| `claude-code-cli` | Anthropic's Claude Code (CLI runner) | — (override only) | roadmap |
| `openhands` | OpenHands issue resolver | — | roadmap |
| `swe-agent` | SWE-agent | — | roadmap |
| `pr-agent` | Qodo/PR-Agent | — | roadmap |

`backend` is a plain string. The tool follows the provider; an explicit `backend` override lets you
pin one or adopt a roadmap adapter later without touching the rest of the pipeline.

The GitHub renderer renders only backends that are started by a pull-request comment (the
`PR_COMMENT` invocation kind, which is how Codex runs). The Claude Code implement backend needs a
different kind (`CI_COMPONENT`), so validation (V-S08) rejects an `implement` stage on GitHub until
that kind can be rendered.

---

## 3a. Skills — content vs. wiring

Two distinct concepts, cleanly layered so the domain knowledge is reusable and portable:

| Concept | Is | Lives in | Referenced by |
|---|---|---|---|
| **Skill** | The reusable *methodology/content* for a task — checklist, rubric, output format. Provider/backend/language-agnostic. | `.agentic/skills/<id>/SKILL.md` in your repo (reference copies ship in `stagr/templates/skills/<id>/`) | `stages[].skill` |
| **Stage** | An agent *placed in the pipeline graph* (with `depends_on`, overrides). | `.agentic/config.yml` `stages[]` | the pipeline |

Why the split:

- **Skills are the crown jewel** — the portable domain knowledge. A backend adapter maps a skill to
  its own prompt/rule format, so the *same* skill drives any backend.
- **Profiles expand into working stages** that already name the right skill, so a repo adopts a
  ready stage without writing one.
- **No vendor/model assumptions** in a skill, and **no secrets** — skills are templates.

Starter skills: `code-review`, `security-review`. Validation (V-S06) fails if a stage names a skill
whose `SKILL.md` file is missing. The catalog may grow (`planning`, `execution-plan`,
`unit-test-authoring`, `integration-test`, `docs`, `release-notes`).

## 4. Provider/model resolution

Per stage, the model resolves **most-specific-first**:

1. **Stage model** — `stages[].model.default`
2. **Org/account default** — `defaults.models.<provider>.default`

There is **no hidden toolkit fallback**: for an `anthropic` stage (Claude Code consumes a contract
model), if neither layer yields a model the toolkit **fails loudly** and never guesses a version. An
`openai` stage (Codex) supplies its own model, so the rule does not apply to it. This is how "same
provider, different models" or "mix Anthropic and OpenAI" is expressed — independently per stage.

---

## 5. Platform neutrality

The contract is written once and rendered per platform. `platform.type` selects the
renderer (`github` ships first; `gitlab`, `azure_devops`, `bitbucket`, `gitea` follow).
The renderer normalizes platform
concepts:

| Neutral concept | GitHub | GitLab | Azure DevOps |
|---|---|---|---|
| change request | Pull Request | Merge Request | Pull Request |
| trusted roles | `author_association` | project roles | security groups |
| required gate | status check | pipeline job / approval rule | branch policy |
| CI unit | workflow | pipeline | pipeline |

The same `.agentic/config.yml` therefore drives any of them; only layer 4 differs.

---

## 6. Easy vs. granular

- **Newcomer:** set `profile` + `platform`. The profile expands to a default stage graph. Model IDs
  come from `defaults`.
- **Expert:** define `stages` explicitly — per-stage provider/model/backend/triggers/gate/
  dependencies.

Profiles and explicit stages compose: listed stages are **merged onto** the profile's
(same id overrides), so you can accept the standard graph and tweak just one stage.

Profile expansions:

| Profile | Stages |
|---|---|
| `minimal` | review (blocking) |
| `standard` | review (blocking), security (blocking) — independent, neither waits for the other |
| `custom` | none — you define every stage |

---

## 7. Cross-cutting invariants

- **Secrets** are referenced by **name** only; never logged, printed, stored, or placed
  in config.
- **Language-agnostic**: the contract never names a language. How a repo declares what "green"
  means is designed in `design-docs/09-check-stages.md`; the config does not read it yet.

---

## 8. Status & roadmap

- **M1 — contract layer and neutral core (current):** schema, config validation, profiles,
  provider/backend/model resolution, and the stage graph.
- **M2 — GitHub renderer (current):** per-stage, routing, and governance (merge-gate) workflows built
  from the graph. The renderer returns artifacts and never writes files.
- **M3 — CLI (in progress):** `help`, `plan` and `apply` are done (issues #201, #202); `doctor`
  (issue #203) and `init` are next.
- **M4 — more backends & platforms:** OpenHands/SWE-agent/PR-Agent adapters; `claude-code-cli`
  backend; GitLab and Azure DevOps renderers.
