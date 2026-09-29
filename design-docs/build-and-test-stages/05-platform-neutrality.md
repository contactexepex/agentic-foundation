# 05 — Platform Neutrality

Neutrality is the key acceptance criterion of this plan. This document shows how one neutral
contract maps onto different CI/CD platforms, and how Stagr stays honest when a platform cannot
give the same guarantees.

Only GitHub is implemented today. For every other platform this plan delivers the **contract, the
capability declaration, and the conformance vectors** (07) — not a renderer. A renderer for
another platform is a separate, later piece of work that must pass the same vectors.

## What is neutral and what is not

| Layer | Neutral? | Contains |
|---|---|---|
| Config (03) | Yes | `build:`, `stages:`, `execution`, `run`, `observe`. No platform words. |
| Core model | Yes | Stage kind, gate, dependency, `StageResultSignal`, states (02), threat rules (04). |
| Capability descriptor | Yes (shape) | A fixed list of yes/no/level questions each platform answers (below). |
| Renderer | **No** (by design) | Jobs, events, APIs, secret stores, check names for exactly one platform. |

If a core file needs a platform word, the design is wrong (P1).

## The capability descriptor

Each platform renderer declares the answers below in code. The core reads them; it never
special-cases a platform name. It is deliberately small: **only questions whose answer changes what
the core renders, refuses or warns about**. Everything else (for example timeouts, which every
rendered work unit must have) is the renderer's plain duty, not a capability. The descriptor is
not versioned in V1; it changes together with the code in one pull request.

| Capability | Values | Why the core needs it |
|---|---|---|
| `definition_source` | `trusted_base` \| `pr_branch` | Can the pipeline that judges a pull request come from the trusted base (S4)? |
| `attested_outcome` | `in_pipeline` \| `api_query` \| `none` | How the publish unit obtains the platform's own outcome of the work unit (S2) |
| `publisher_identity` | `app` \| `service_account` \| `name_only` | How strongly a result author can be identified (provenance level, below) |
| `head_binding` | yes / no | Can a result be bound to one commit (P6, S9)? |
| `read_foreign_results` | yes / no | Can a trusted unit read results produced by another system (observed mode)? |
| `fork_isolation` | `no_secrets_for_forks` \| `none` | Do fork pipelines run without secrets by default? |
| `ephemeral_runners` | yes / no | Is a clean runner per job the default or available (S14)? |
| `attempt_lineage` | yes / no | Does the platform expose a monotonic attempt identity (an attempt token, totally ordered in time), so re-run attempts of one result can be ordered and told apart from separate jobs (02)? If not, `no` |

### What the core does with the answers

| Situation | Behaviour |
|---|---|
| Blocking **managed** stage and any of `attested_outcome=none`, `head_binding=no` | **Refuse to render** (error). The guarantee cannot be met (P5) |
| **Any** managed stage (blocking or advisory) and `ephemeral_runners=no` | **Refuse to render** (error). Untrusted pull-request code on a reusable runner can leave files or binaries that a later trusted job or another build runs; a non-blocking result does not reduce that isolation risk |
| Blocking stage and `publisher_identity=name_only` | Refuse. Provenance level too weak (below) |
| `definition_source=pr_branch` | Render, but `doctor` warns that the pull request can alter the definition that judges it, and an empty `merge.protected_paths` becomes an error (04) |
| `fork_isolation=none` | Managed stages refuse forks anyway (S13); the fork policy for review stages must be `DENY` |
| Observed stage and `read_foreign_results=no` | Refuse to render |
| Observed or managed stage and `attempt_lineage=no` | Attempts cannot be ordered, so any duplicate result of the same name is ambiguous and not passed |
| Advisory stage | The result-integrity capabilities above (`attested_outcome`, `head_binding`, provenance level) may be weaker, because the stage cannot block and so cannot be a false pass. Isolation capabilities (`ephemeral_runners`, `fork_isolation`) are **not** relaxed |

## Provenance levels

"Who produced this result" must be strong enough that a name cannot be spoofed.

| Level | Identity | Example | Allowed for blocking? |
|---|---|---|---|
| L3 | Registered application / integration id **dedicated to that tool** | A code-analysis service's own GitHub App | Yes |
| L2 | Named service account or token owner | GitLab project access token user, Azure service principal | Yes |
| L1 | Result name / label only, **or an identity shared by every pipeline of the repository** | A status called "build"; the CI platform's built-in Actions identity | **No** for observed stages |

The last case matters: on a platform where every pipeline result is authored by the same built-in
identity, a pull request that can edit its own pipeline definition can create a result with any
name. Such a result is only L3-strong when `definition_source` is `trusted_base`; otherwise it is
treated as L1 and cannot satisfy a blocking observed stage. `observe.producer` (03) is matched
against the identity, never the display name.

## Neutral concept to platform mapping

This table is the contract each future renderer must satisfy. Cells marked **verify** are
believed correct but must be checked against current vendor documentation before that
platform's renderer is built (delivery Phase 6). The fact-check pass on this plan reviews each
row.

| Neutral concept | GitHub (implemented) | GitLab CI | Azure DevOps Pipelines | Bitbucket Pipelines | Jenkins |
|---|---|---|---|---|---|
| Trigger: pull request opened / updated | `pull_request_target` types opened, synchronize, ... | Merge request pipeline (`merge_request_event` rule) | Branch policy build validation (Azure Repos); YAML `pr:` trigger (GitHub repos) | `pull-requests` pipeline | Multibranch PR discovery |
| Work unit | Job with `contents: read`, no secrets | Job in the pipeline | Job in a stage | Step | Stage / agent |
| Definition source (S4) | Base branch (`pull_request_target`) | PR branch by default; a pipeline execution policy with `override_project_ci` can replace it (Ultimate tier only). Compliance pipelines are deprecated | PR branch by default; a required-template check exists but covers only pipelines that use the protected resource | PR branch (**verify**) | PR head for same-repository PRs; target branch for untrusted fork PRs (branch-source trust setting) |
| Attested outcome | `needs.<job>.result` in the same workflow (`success`, `failure`, `cancelled`, `skipped`; the publish job needs `if: always()`) | Job status via pipeline API (**verify**) | `dependsOn` + result condition (**verify**) | Not in-pipeline; API query (**verify**) | Build result via API (**verify**) |
| Publish unit | Job holding the GitHub App key, no checkout | Job or external service using a service account (**verify**) | Job with service connection (**verify**) | Job or external service using an access token (**verify**) | Post-build step or external service |
| Publisher identity | App id (L3) | Service account (L2) (**verify**) | Service principal (L2) (**verify**) | Access-token owner (L2) (**verify**) | Credential owner (L2) |
| Result carrier | Check Run named `stagr/<id>`, head SHA | Commit status / external status check (**verify**) | Pull request status on an iteration; the status policy resets on new changes and can require an authorized account | Build status on commit, keyed by `key`; the merge check cannot select by key | Build status on commit |
| Required for merge (native) | Branch protection / ruleset requires the check | "Pipelines must succeed" + external status checks (**verify**) | Branch policy: status or build validation | Merge check: successful builds | SCM plugin / provider rule |
| Fork isolation | **None natively:** `pull_request_target` gives fork PRs secrets and a write token, so the eligibility unit must deny forks (fork policy, design doc `05-governance-and-trust.md`) | A fork MR pipeline runs in the fork project with the fork's config and variables | Fork builds withhold secrets by default for GitHub-hosted repos; not for GitHub Enterprise Server (**verify** for Azure Repos) | Secured variables withheld for forks (**verify**) | Fork trust policy (**verify**) |
| Timeout | `timeout-minutes` | `timeout` | `timeoutInMinutes` (must be non-zero; `0` means the maximum) | `max-time` | `timeout(time:, unit:)` wrapper |
| Cancel superseded | `concurrency`, also at job level (**verify**: one running and one pending job per group, a newer pending job replaces an older pending one when `cancel-in-progress` is false, so a job that must always run, such as publish, gets a group nobody else shares) | `interruptible` / `workflow:auto_cancel` | GitHub repos: `pr.autoCancel` (default true); Azure Repos: **verify** | Not verified | `disableConcurrentBuilds(abortPrevious: true)` / `milestone()` |
| Secrets by name | Repository / environment secrets | CI/CD variables (masked/protected) | Variable groups / Key Vault | Repository / workspace variables (secured) | Credentials store |

Two things to notice:

1. **Not every platform can meet every rule natively.** The largest gap is `definition_source`:
   several platforms run the pull request's own pipeline file. The capability descriptor makes
   that visible instead of hiding it, and protected paths (04) compensate.
2. **Observed mode is the universal adapter.** A team on any platform can already use
   `execution: observed`, because reading one named, producer-verified result needs only
   `read_foreign_results` and `head_binding`.

## Renderer responsibilities

A platform renderer for check stages must:

1. Render the three units (eligibility, work, publish) or, for observed stages, the
   eligibility and publish units only.
2. Declare its capability descriptor truthfully and completely, and give every work unit a timeout
   and its own cancel-superseded concurrency (04, S6 and T11). Where the platform lets a queued
   job replace a pending one, keep eligibility and publish out of one shared group (06, "The lease").
3. Keep all platform words (event names, job keys, API paths) inside its own package.
4. Pass every conformance vector (07) using only the neutral interface.
5. Carry the same stage-result contract (`StageResultSignal`, schema version 1). Only the
   *carrier* differs per platform.

## The result carrier stays small

A platform transports the neutral `StageResultSignal` (stage id, head, state, conclusion) in
whatever native form it offers — a check run, a commit status, a policy status. The carrier must
support: identify producer, bind to head, distinguish states, be re-published for the same head.
A platform whose carrier cannot do all four gets `head_binding=no` or `publisher_identity=name_only`
and is limited to advisory stages until that changes.

The descriptor and table are intentionally short and only as detailed as the current GitHub
implementation needs. They are the checklist a second platform is reviewed against, not a
framework built ahead of one.

## Adding a platform (summary)

1. Write the capability descriptor and mapping row; get it reviewed against vendor docs.
2. Implement the renderer package behind the existing renderer interface.
3. Run the shared conformance vectors; fix until all pass.
4. Add a `platform.type` value and its docs page.

No core, schema-shape or model change is needed for step 2 or 3. If one is, the neutral contract
was incomplete and is fixed once, for everyone (P8).
