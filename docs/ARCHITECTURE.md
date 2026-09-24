# agentic-foundation — architecture

This is the design of the toolkit: the mental model, the layers, and how it stays
**easy for newcomers** yet **granular for experts**, across **any provider/model**,
**any SCM platform**, and **any language**.

---

## 1. Mental model: a pipeline is a graph of stages

A repository's agentic pipeline is an **ordered, extensible graph of stages**. Each
**stage is one agent** in the SDLC/STLC — `plan`, `implement`, `security`, `test`,
`integration-test`, `review`, `docs`, `release`, or `custom` — bound to:

- a **provider + model** (the knob — `anthropic` or `openai` today; mix per stage),
- a **backend** (the executor/tool; derived from the provider, overridable),
- **triggers** (issue label, PR/MR opened/updated, comment command, push, schedule, manual),
- a **gate** (advisory = comment only; blocking = emits a required status check),
- **dependencies** (`depends_on`) that define the graph edges.

`implement` and `review` are just two built-in stage *types*; they are not special.
The same contract expresses a two-stage pipeline or a full SDLC of a dozen stages.

```
issue ──▶ [plan] ──▶ [implement] ──┬─▶ [security]          ──┐
                                   ├─▶ [integration-test]  ──┤─▶ gates ─▶ PR/MR ─▶ (auto_merge?) ─▶ human
                                   └─▶ [review]            ──┘
```

---

## 2. Layers (separation of concerns)

The toolkit is deliberately split so each concern can change without disturbing the others.

| Layer | Responsibility | Configured by |
|---|---|---|
| **1. Contract** | Declarative, platform-neutral description of the pipeline. | `.agentic/config.yml` (this schema) |
| **2. Provider adapters** | Talk to a model vendor (Claude / OpenAI / Gemini / local / gateway). Give true provider-agnosticism. | `providers`, `defaults.models`, `models.aliases` |
| **3. Agent tools** | Execute a stage. The tool is derived from the provider (`anthropic` → Claude Code, `openai` → Codex); roadmap adapters wrap other OSS agents. | `stages[].provider` (or `stages[].backend` to pin) |
| **4. Platform/SCM adapters** | Render the neutral pipeline into a concrete CI system and normalize concepts (PR↔MR, roles, checks). | `platform` |
| **5. Installer / CLI** | `init` / `doctor` / `plan` / `apply`: validate, render for the target platform, open the bootstrap PR/MR. | — |

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

| Backend (tool) | Wraps | Derived from | Rendered today? |
|---|---|---|---|
| `claude-code-action` | Anthropic's Claude Code | `anthropic` | ✅ implement |
| `codex` | OpenAI Codex | `openai` | ✅ review, security |
| `generic` | Built-in prompt-runner (provider adapter + prompt + tools) | — | roadmap |
| `openhands` | OpenHands issue resolver | — | roadmap |
| `swe-agent` | SWE-agent | — | roadmap |
| `pr-agent` | Qodo/PR-Agent | — | roadmap |
| `custom` | Any action ref / container image via `backend.uses` | — | roadmap |

`backend.with` passes tool-specific inputs through unchanged. The tool follows the provider;
an explicit `backend` override lets you pin one or adopt a roadmap adapter later without
touching the rest of the pipeline.

---

## 3a. Skills and agents — content vs. wiring

Three distinct concepts, cleanly layered so the domain knowledge is reusable and portable:

| Concept | Is | Lives in | Referenced by |
|---|---|---|---|
| **Skill** | The reusable *methodology/content* for a task — checklist, rubric, output format. Provider/backend/language-agnostic. | `stagr/templates/skills/<id>/SKILL.md` (+ your own via the `skills` registry) | `stages[].skill` |
| **Agent preset** | A *pre-wired stage* — type + default skill + provider + gate + triggers, and an **optional** model binding (presets may omit it; the Anthropic implementer resolves via `defaults`, Codex supplies its own). | `stagr/templates/agents/<id>.yml` | `stages[].from` |
| **Stage** | An agent *placed in the pipeline graph* (with `depends_on`, overrides). | `.agentic/config.yml` `stages[]` | the pipeline |

Why the split:

- **Skills are the crown jewel** — the portable domain knowledge. The `generic` backend consumes a
  skill directly as its instructions; other backends' adapters map it to their own prompt/rule format,
  so the *same* skill drives any backend.
- **Layered & overridable** — register a skill by id, pin a `version`, or `extends` a built-in with a
  house style; org→team→repo layering via `extends` applies to skills too.
- **Agent presets** make profiles expand into *working* agents, and let a repo adopt a ready stage
  with one line (`from: code-review`) then override only what it needs.
- **No vendor/model assumptions** in a skill, and **no secrets** — skills are templates; guardrails
  (untrusted-input handling) apply to everything a skill ingests.

Starter skills: `code-review`, `security-review` (with matching agent presets). The catalog grows
(`planning`, `execution-plan`, `unit-test-authoring`, `integration-test`, `docs`, `release-notes`).

## 4. Provider/model resolution

Per stage, per change tier, the model resolves **most-specific-first**:

1. **Per-request override** (dispatch input / command)
2. **Stage model** — `stages[].model.tiers.<tier>` → `.default`
3. **Org/account default** — `defaults.models.<provider>.tiers.<tier>` → `.default`

A resolved value that matches a `models.aliases` name expands to that alias's model ID
for the stage's provider. `tier` (trivial/standard/complex) comes from the deterministic
classifier (change size + paths) only when tiering is on. There is **no hidden toolkit
fallback**: for an `anthropic` stage (Claude Code consumes a contract model), if none of layers 1–3
yields a model the toolkit **fails loudly** and never guesses a version. An `openai` stage (Codex)
supplies its own model, so the rule does not apply to it. This is how "same provider, different
models" or "mix Anthropic and OpenAI" is expressed — independently per stage.

---

## 5. Platform neutrality

The contract is written once and rendered per platform. `platform.type` selects the
renderer (`github` ships first; `gitlab`, `azure_devops`, `bitbucket`, `gitea` follow).
`platform.host` supports self-hosted / enterprise. The renderer normalizes platform
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

- **Newcomer:** set `profile` + `platform` (+ `build`). The profile expands to a default
  stage graph. Model IDs come from `defaults` (or the org base via `extends`).
- **Expert:** define `stages` explicitly — per-stage provider/model/tiers/backend/
  triggers/gate/dependencies, per-stage budgets, custom backends, and org→team→repo
  layering via `extends`.

Profiles and explicit stages compose: listed stages are **merged onto** the profile's
(same id overrides), so you can accept the standard graph and tweak just one stage.

Profile expansions:

| Profile | Stages |
|---|---|
| `minimal` | implement, review (advisory; humans merge) |
| `standard` | implement, review (blocking), security (advisory) |
| `full` | plan, implement, security, test, integration-test, review, docs |
| `custom` | none — you define every stage |

---

## 7. Cross-cutting invariants

- **Secrets** are referenced by **name** only; never logged, printed, stored, or placed
  in config. Always redacted from observability output.
- **Language-agnostic**: `build.commands` are the only definition of "green"; stages run
  exactly those.
- **Budgets, guardrails, observability** apply across stages (with per-stage overrides
  where it makes sense) and adapt to whatever an org/team/user configures — nothing about
  hosting, endpoints, or telemetry is hardcoded.

---

## 8. Status & roadmap

- **M1 — contract layer (current):** schema, config template, docs. Platform-neutral,
  stage-graph, profiles, provider/model resolution, backends, and cross-cutting policy
  defined as the contract.
- **M2 — GitHub renderer + generic backend:** installer renders the graph to GitHub
  Actions; `generic` runner + `claude-code-action`/`pr-agent` adapters.
- **M3 — CLI:** `doctor`, `plan`, `apply`.
- **M4 — more backends & platforms:** OpenHands/Codex/SWE-agent adapters; GitLab and
  Azure DevOps renderers.
