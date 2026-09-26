# Security & secrets — least privilege and principal isolation

stagr renders workflows that hold real credentials (model API keys, a push token, a remediation
PAT) and drive untrusted PR content past them. The rendered pipeline must be secure **by
construction**, not by convention. This page states the guarantees; the threat model is in
[trust-and-correctness.md](trust-and-correctness.md), and the base contract in
[`../../AGENTS.md`](../../AGENTS.md).

## Principal isolation (the core rule)

Distinct machine principals stay isolated even though one team owns them:

- The **untrusted implementer** (e.g. Codex when it acts, or any implementing agent) must **never**
  reach the **trusted publisher** or the **push credential**.
- The workflow `GITHUB_TOKEN`, the remediation PAT, `github-actions[bot]`, and any GitHub App
  identity have **different capabilities that must not be conflated**. A stage gets the identity
  its job requires and no other.
- **Fork PRs never drive automation** and never reach a credential. Automation runs only for
  trusted `author_association` on same-repo branches.

## Least privilege per stage

Every rendered job declares the **minimum** `permissions:` it needs, scoped to the stage:

- A review/analysis stage that only reads code and posts comments gets read scopes + the narrow
  write it needs to comment — never `contents: write`.
- Only the **publish/merge** step carries write/merge scope, and it is the base-controlled gate,
  not an agent stage.
- Writes produced by an agent are **buffered and applied in a separate, scoped-permission step**,
  so an agent's output cannot exercise a broad token directly.
- No stage is granted a capability "just in case." If a stage does not need a scope, it does not
  get it.

## Secrets model

- **Referenced by name, never by value.** Config and templates name a secret
  (`${{ secrets.NAME }}`); a secret value never appears in config, logs, prompts, or a rendered
  file.
- **Never logged or printed.** Secrets are redacted from all observability output
  ([audit-and-provenance.md](audit-and-provenance.md)); model-provider trace/sensitive-data
  inclusion stays disabled unless explicitly justified.
- **Org-scoped by default.** Keys live as **organization/environment secrets** shared to selected
  repos, so onboarding a repo needs no per-repo secret setup
  ([onboarding-and-config.md](onboarding-and-config.md)). Non-secret provider metadata
  (`base_url`, `api_version`, `deployment`) may live in config; credentials never do.

## Execution stays on the user's side of the line

The agent-backend seam ([concepts.md](concepts.md#backend-and-the-agent-backend-seam)) guarantees
that a backend runs **either** in the user's CI runner (CLI / GitHub-native) **or** by dispatching
to a provider's cloud — **never inside a stagr-hosted process or service**. stagr writes wiring; it
never becomes a runtime that holds the user's code or keys. This keeps the trust surface small and
is a first-class selling point, not an implementation detail.

## Supply-chain integrity

- **Actions pinned to immutable commit SHAs**, not floating tags.
- **No `uses: ./…`** or repository-sourced script executed by the gate over PR content.
- Renderer output is deterministic and reviewable, so what runs in CI is exactly what the contract
  declared.

## What "secure" means here

A rendered pipeline is secure only when: no stage holds a scope it does not need; the implementer
principal provably cannot reach the push credential; every secret is name-referenced and redacted;
fork PRs drive nothing; and there is a negative test for each of these in
[edge-cases.md](edge-cases.md) (e.g. a sentinel injected into every untrusted PR field must never
reach the build/publish step or a credential).
