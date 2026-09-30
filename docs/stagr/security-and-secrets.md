# Security & secrets — least privilege and principal isolation

stagr renders workflows that hold real credentials (model API keys, a push token, a remediation
token) and drive untrusted PR content past them. The rendered pipeline must be secure **by
construction**, not by convention. This page states the rules; the threat model is in
[trust-and-correctness.md](trust-and-correctness.md) and the base contract in
[`../../AGENTS.md`](../../AGENTS.md).

## Principal isolation (the core rule)

Distinct machine principals stay isolated even though one team owns them:

- The **untrusted implementer** (an implementing agent) must **never** reach the **trusted
  publisher** or the **push credential**.
- The workflow `GITHUB_TOKEN`, the remediation token, `github-actions[bot]` and any GitHub App
  identity have **different capabilities that must not be conflated**. A stage gets the identity its
  job requires and no other.
- **Fork PRs never drive the privileged automation.** The agent, review and merge workflows run
  only for trusted `author_association` on same-repo branches, and a fork PR never reaches a secret
  or a write, publisher or merge token. The exception is CI: `validate.yml` triggers on
  `pull_request`, so it runs checkout and the repo's validation for a fork PR. That job runs under
  GitHub's restricted fork token with **no secrets**, but the fork's code can read that job's
  read-only `GITHUB_TOKEN`. "Forks drive nothing" therefore means the privileged workflows, not
  Validate.

## Least privilege per stage

Every rendered job declares the **minimum** `permissions:` it needs, scoped to the stage:

- A review or analysis stage that only reads code and posts comments gets read scopes plus the
  narrow write it needs to comment, never `contents: write`.
- Only the **publish or merge** step carries merge scope, and it is the base-controlled gate, not an
  agent stage.
- Agent-produced writes are **buffered and applied in a separate, scoped-permission step**, so an
  agent's output cannot exercise a broad token directly.
- No stage is granted a capability "just in case."

**Where this repository's own workflows stand today** (Stagr does not render an implementer yet).
`authorized-engineering-task.yml` already follows the buffered pattern: its Codex job has only
`contents: read` and uploads its result, and a separate job pushes it. Two things fall short:

- `claude-code-implementor.yml` runs `claude-code-action` with `contents: write` and
  `pull-requests: write` on the same job, with no buffered-output or separately scoped apply step.
  Its "work on a feature branch, never push to main" rule is an instruction in the prompt, not
  something the token enforces, so without a server-side rule that blocks it the token could push
  to the default branch.
- `request-codex-review-on-push.yml`, `request-final-security-review.yml` and
  `resolve-fixed-codex-review-threads.yml` use the `REMEDIATION_TOKEN` secret, a personal access
  token with Contents and Pull requests read/write (the workflow comments say so). That is more than
  posting a comment needs. The token is set in the environment of a whole shell step, so every
  command in that step can read it, and it is not confined to one isolated posting step.

The remediation token is never passed to a model, and secrets are referenced by name and never
printed. Narrowing these (separately scoped steps, a minimal commenting identity)
is not done.

## Secrets model

- **Referenced by name, never by value.** Config and templates name a secret
  (`${{ secrets.NAME }}`); a secret value never appears in config, logs, prompts or a rendered
  file.
- **Never logged or printed.** Secrets are kept out of all observability output
  ([audit-and-provenance.md](audit-and-provenance.md)), and model-provider trace and
  sensitive-data inclusion stays disabled unless explicitly justified.
- **Org-scoped by default.** Keys live as **organization or environment secrets** shared to selected
  repos, so onboarding a repo needs no per-repo secret setup
  ([onboarding-and-config.md](onboarding-and-config.md)). Credentials never live in config.

## Execution stays on the user's side of the line

A backend runs **either** in the user's CI runner **or** by dispatching to a provider's cloud,
**never inside a stagr-hosted process or service** ([`../CHARTER.md`](../CHARTER.md) §2). stagr
writes wiring; it never becomes a runtime that holds the user's code or keys. This keeps the trust
surface small.

## Supply-chain integrity

- **Actions are pinned to immutable commit SHAs**, not floating tags.
- **No `uses: ./…`** and no repository-sourced script executed by the gate over PR content.
- Renderer output is deterministic and reviewable, so what runs in CI is exactly what the contract
  declared.

## What "secure" means here

A rendered pipeline is secure only when: no stage holds a scope it does not need; the implementer
cannot merge or reach the remediation or publisher credential; every secret is referenced by name
and never printed; fork PRs drive no privileged workflow (Validate aside); and each of these has a
negative test (for example, a sentinel injected into every untrusted PR field must never reach a
build or publish step or a credential).
