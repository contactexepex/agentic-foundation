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
- **Fork PRs never drive the privileged automation** — the agent, review, and merge lanes run only
  for trusted `author_association` on same-repo branches, and a fork PR never reaches a **secret or a
  write/publisher/merge token**. (**Stated honestly:** the shipped `validate.yml` triggers on
  `pull_request`, so it *does* run CI — checkout + `build.commands` — for a fork PR. That runs under
  GitHub’s **restricted fork token** with **no secrets**, but the fork’s `build.commands` can read the
  **read-scoped `GITHUB_TOKEN`** in that job; hardening the build against even the read token is a
  consideration. So “forks drive nothing” means the privileged lanes, not Validate/CI.)

## Least privilege per stage

**Design intent [target]:** every rendered job declares the **minimum** `permissions:` it needs,
scoped to the stage:

- A review/analysis stage that only reads code and posts comments gets read scopes + the narrow
  write it needs to comment — never `contents: write`.
- Only the **publish/merge** step carries merge scope, and it is the base-controlled gate, not an
  agent stage.
- Agent-produced writes are **buffered and applied in a separate, scoped-permission step**, so an
  agent’s output cannot exercise a broad token directly.
- No stage is granted a capability “just in case.”

**Current state [shipped], stated honestly — neither shipped agent lane is read-only today:**

- The **Claude implementer job** runs `claude-code-action` **with `contents: write` and
  `pull-requests: write`** on the same job — no buffered-output / separately-scoped apply step.
- The **Codex review and security lanes** carry the **remediation PAT** (`CODEX_PAT`, a real-user
  credential with **Contents R/W + Pull Requests R/W**) to author review comments as a trusted user.
  The PAT is exposed **step-wide**: it is set in the environment of the **whole orchestration shell
  step** (which also runs an authenticated `/user` lookup before posting), so **every command in that
  step can read it** — it is **not** confined to a single isolated post step. So the review/security
  lane is **not read-scoped** and holds a publisher-class credential.

So the least-privilege, buffered-apply, and minimal-commenting-identity goals above (including
splitting PAT login/post into separately-scoped steps) are **[target] hardening items**
([roadmap.md](roadmap.md)), not enforced guarantees today. **Honest limitation:** the implementer’s
`GITHUB_TOKEN` holds `contents: write` + `pull-requests: write`, so **absent a server-side ruleset it
can push to the default branch or call the merge API** — the “work on a feature branch” behaviour is
**prompt-driven, not enforced**; a scoped publisher and/or a required ruleset is **[target]**. What
*does* hold today: secrets are name-referenced and redacted, the PAT is never handed to the model, and
**fork PRs drive no privileged lane**.

## Secrets model

- **Referenced by name, never by value.** Config and templates name a secret
  (`${{ secrets.NAME }}`); a secret value never appears in config, logs, prompts, or a rendered
  file.
- **Never logged or printed.** Secrets are redacted from all observability output
  ([audit-and-provenance.md](audit-and-provenance.md)); model-provider trace/sensitive-data
  inclusion stays disabled unless explicitly justified.
- **Org-scoped by default.** Keys live as **organization secrets** shared to selected
  repos, so onboarding a repo needs no per-repo secret setup
  ([onboarding-and-config.md](onboarding-and-config.md)). Non-secret provider metadata
  (`base_url`, `api_version`, `deployment`) may live in config; credentials never do.

## Org secret sharing

Secrets live at the **org scope** and are shared to selected repos. This removes
per-repo secret setup: any repo covered by the org automatically inherits those secrets with no
local configuration step.

**What a standard pipeline needs.** The table below lists the default secret names a standard
stagr-rendered pipeline requires. `stagr doctor` prints the names your specific config resolves to.

| Secret name | Stage that uses it | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Implement (Claude Code) | Anthropic API key for the implementer |
| `REMEDIATION_TOKEN` | Review, Security (Codex) | PAT used by Codex for review comments, security review, and thread resolution (the `codex_review_secret` default) |

Secrets are **always referenced by name** — `${{ secrets.ANTHROPIC_API_KEY }}` in a rendered
workflow — and the name is what lives in `.agentic/config.yml`. A secret value never appears in
config, templates, logs, or a rendered file.

The default names above are overridable in `.agentic/config.yml`
(e.g. `providers: { anthropic: { api_key_secret: MY_CLAUDE_KEY } }`). **Caveat:** the shipped
`implementor.yml` template currently hardcodes `ANTHROPIC_API_KEY`; changing that name in config
today leaves the rendered job without its credential even though `doctor` succeeds — use the
default name until the resolved name is wired into the template
([onboarding-and-config.md](onboarding-and-config.md)).

**How to share at org scope (GitHub).** In your organization’s settings under
*Secrets and variables → Actions*, create each secret and set repository access to
**Selected repositories** (add each repo) or **All repositories**. The pipeline reads each
secret by name; no per-repo copy of the value is needed.

**Confirming required names.** `stagr doctor` reports the secret names the config requires (e.g.
`providers.anthropic.api_key_secret → ANTHROPIC_API_KEY`). It does **not** probe GitHub to verify
those names are populated at the org scope; confirming that each name resolves is a one-time
manual step at onboarding ([onboarding-and-config.md](onboarding-and-config.md)).

**Validation.** `validate_config.py` confirms that every secret-name field in the config holds an
identifier (e.g. `ANTHROPIC_API_KEY`) rather than a literal credential value. A value that does not
match the identifier format (`[A-Za-z_][A-Za-z0-9_]*`) fails the check so a committed secret is
caught before it reaches a remote.

## Execution stays on the user’s side of the line

The agent-backend seam ([concepts.md](concepts.md#backend-and-the-agent-backend-seam)) guarantees
that a backend runs **either** in the user’s CI runner (CLI / GitHub-native) **or** by dispatching
to a provider’s cloud — **never inside a stagr-hosted process or service**. stagr writes wiring; it
never becomes a runtime that holds the user’s code or keys. This keeps the trust surface small and
is a first-class selling point, not an implementation detail.

## Supply-chain integrity

- **Actions pinned to immutable commit SHAs**, not floating tags.
- **No `uses: ./…`** or repository-sourced script executed by the gate over PR content.
- Renderer output is deterministic and reviewable, so what runs in CI is exactly what the contract
  declared.

## What “secure” means here

A rendered pipeline is secure only when: no stage holds a scope it does not need; the implementer
principal’s write scope is **narrowed so it cannot merge or reach the remediation/publisher
credential** (**[target]** — today it holds `contents`/`pull-requests: write` and relies on a
server-side ruleset to prevent a direct merge to the default branch); every secret is
name-referenced and redacted; fork PRs drive no privileged lane (Validate/CI aside); and there is a
negative test
for each of these in
[edge-cases.md](edge-cases.md) (e.g. a sentinel injected into every untrusted PR field must never
reach the build/publish step or a credential).
