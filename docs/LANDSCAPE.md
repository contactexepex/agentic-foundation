# Landscape — how agentic-foundation differs

A scan of the open-source ecosystem (Sept 2026) for tools that automate an
"AI implements → AI reviews → CI-gated PR" workflow. Star/contributor figures are
approximate and move; treat them as orders of magnitude.

## The market covers halves, not the whole

The mature, widely-used OSS projects each own **one half** of the pipeline:

| Project | ~Stars | Role | Provider-agnostic | Lang-agnostic | Drop-in/CI | Maintained |
|---|---|---|---|---|---|---|
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | ~89k | **Implement** (+ opens PRs) | ✅ (LiteLLM) | ✅ | ✅ Action | ✅ |
| [Aider](https://github.com/Aider-AI/aider) | ~49k | Implement (local CLI) | ✅ | ✅ | ❌ not a PR/CI bot | ✅ |
| [PR-Agent / Qodo](https://github.com/qodo-ai/pr-agent) | ~13k | **Review** only | ✅ (LiteLLM) | ✅ | ✅ App/Action | ✅ community |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | ~20k | Implement (patches) | ✅ | ✅ | ⚠️ research-grade | ✅ |
| [claude-code-action](https://github.com/anthropics/claude-code-action) | ~9k | Both (implement+review) | ⚠️ Claude-only | ✅ | ✅ Action | ✅ |
| [openai/codex](https://github.com/openai/codex) + codex-action | ~126k | Implement+review | ⚠️ OpenAI/Azure | ✅ | ✅ Action | ✅ |
| [reviewdog](https://github.com/reviewdog/reviewdog) | ~10k | CI gate (non-AI) | n/a | ✅ | ✅ | ✅ |
| [Danger](https://github.com/danger/danger) | ~6k | PR-rule gate (non-AI) | n/a | ✅ | ✅ | ✅ |
| [Sweep](https://github.com/sweepai/sweep) | ~8k | Implement | limited | ✅ | ⚠️ pivoted to JetBrains | ❌ |
| [AutoPR](https://github.com/irgolic/AutoPR) | ~1.4k | Implement | weak | ✅ | ✅ | ❌ archived |

## Each leader misses at least one axis

- **claude-code-action** — closest to "implement + review + CI, drop-in Action" but **model-locked to
  Claude** (multi-cloud, not multi-vendor).
- **PR-Agent** — best provider-agnostic, config-driven **reviewer**, but does **not implement**.
- **OpenHands** — best provider-agnostic **implementer** that opens PRs, but review isn't a
  first-class, config-tuned role.
- **Aider / SWE-agent** — strong provider-agnostic implementers; no reviewer or CI gate.
- **codex** — implement + review + CI, but OpenAI/Azure-centric.

The de-facto 2026 pattern is a **DIY stack**: OpenHands (implement) + PR-Agent (review) + existing CI
as the gate. Nobody ships it as one governed, configurable contract.

## The open niche agentic-foundation fills

No mature, high-contributor OSS project provides a **drop-in, config-driven contract** that:

- models an **arbitrary graph of SDLC/STLC stages** (not a fixed implement+review pair);
- binds **any provider/model per stage** (mix vendors and frontier models freely);
- **composes** the agents above as pluggable **backends** instead of reinventing them;
- renders to **any SCM platform** (GitHub/GitLab/Azure DevOps/…);
- adds **deterministic model tiering**, **fast-path routing**, a **fail-closed auto-merge gate**,
  **layered org→team→repo config**, **budgets**, **guardrails**, and **observability** — all
  configurable, nothing hardcoded.

The nearest commercial analog to the layered-governance idea is **Qodo's Rule System (beta)** —
proprietary and reviewer-only. The strategic position for agentic-foundation is therefore an
**orchestration / contract layer**, not another agent.

## Overlap risks to watch

- **claude-code-action** could add multi-vendor model support.
- **Qodo's Rule System** is edging toward configurable multi-repo governance.

Both are proprietary or partial today, but worth tracking.
