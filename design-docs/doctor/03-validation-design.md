# Doctor — Validation Design

Part of the [doctor design set](README.md). Supersedes the "Environment validation" section of
`design-docs/07-validation.md` once accepted. Constraints (C#) and facts (F#) are in
[01-constraints.md](01-constraints.md).

## Order and status model

1. Static validation (V-S01 to V-S09, V-S11, V-S14) runs first through `load_render_inputs`, the same
   function `plan` and `apply` use. Any static error stops doctor before any environment check.
2. Environment checks run next and each prints one result.

| Status | Meaning | Fails the exit code |
|---|---|---|
| `PASS` | Checked and correct | No |
| `WARN` | Checked; risky but not broken | No |
| `ERROR` | Checked and wrong, or could not be checked in `--ci` | **Yes** |
| `SKIP` | Not checked. Local mode: cannot verify here. `--ci`: blocked by an earlier ERROR, or an optional probe has no token or no access (D7, 06) | No |

Rule: **a live check that cannot run in `--ci` is an ERROR, never a silent SKIP.** `--ci` is the
authoritative mode, so a missing input there is a setup mistake. The only exceptions are the two
optional probes (V-E03, V-E04 live), which `SKIP` without `STAGR_PLATFORM_TOKEN`, or when GitHub answers 401, 403 or 404 to it. Only a
positive finding from a probe is an ERROR or WARN ([06](06-deployment-scenarios.md)).

## Two sources of truth

- **Requirements** are derived offline from the same render the pipeline uses: the secret names per stage
  (`ExecutionPlan.required_secrets`), the private-key secret name, the App permissions, the declared
  `permissions:` blocks, and `trusted_roles`. They drive both the local checklist and the CI checks, so
  the two cannot disagree.
- **Observations** come only from CI (presence flags, the App API). Doctor compares them to requirements.

## Checks

### V-E01 — Backend secrets present

- **Requirement:** every secret env name in every stage's `required_secrets` (after alias resolution).
- **Local:** `SKIP`; the names and stages go in the checklist.
- **`--ci`:** read presence flags (D4). Each missing secret is an ERROR naming the secret and the stage.
- **`--ci`, central run (D10):** when no `STAGR_HAS_*` flag is set and `STAGR_PLATFORM_TOKEN` is present, doctor
  lists the target repo's secret names and the org secrets available to it (F8) and compares them to the
  requirement. Failure to list (401, 403, 404) is an ERROR, because this is the only source for the check.
- **Why flags in the repo pipeline, not the API:** listing secrets needs admin, and `GITHUB_TOKEN` cannot do it (F2). The
  `secrets` context already answers "does it exist?" for repo, environment and org secrets (F1).

### V-E02 — Publisher App

Four sub-checks, reported as separate lines:

| Sub-check | Local | `--ci` |
|---|---|---|
| **a. App ID configured** | PASS (plan/apply already require it) | same |
| **b. Private-key secret present** (`platform.publisher.private_key_secret`) | `SKIP` | presence flag; ERROR names the secret |
| **c. App installed** | `SKIP` | `GET /repos/{r}/installation` with an App JWT (F3); `404` is an ERROR naming the App ID |
| **d. Permissions sufficient** | `SKIP` | compare `installation.permissions` to the required union; ERROR lists each missing or too-weak permission |

In a central run, b is answered from the secrets API (D10). c and d need the App key, which a central run
does not hold, so they `SKIP (needs the App key; runs in the repo pipeline)` and the summary says they were
not verified.

If b fails, c and d are `SKIP` (blocked). Levels order `read < write < admin`; installed must be at least
the required level.

**Required union (D5).** The platform renderer declares, per artifact, the App permissions it needs, and
doctor unions them. Today the required set exists only as a hand-written table in
`docs/CONFIGURATION.md` and the workflows mint tokens without `permission-*` narrowing (F5). The
implementation adds a declared-permissions field to each rendered artifact, fills it in the GitHub
renderer, and makes the docs table match. Doctor never hardcodes a global permission list.

**D3 (decided: option A) — how c and d authenticate.** The App's permissions can only be read with an
App JWT, which is signed with the private key (F3, F4). In `--ci`, the workflow passes the key to doctor;
doctor signs a 10-minute JWT **in memory** and never prints, logs or writes the key. This amends the
"no secret value is read" rule for this one command.

Conditions: same-repo trusted triggers only (push to the default branch, `workflow_dispatch`); never
fork or untrusted PR code; the key is used only to sign.

Rejected: option B (never read the key; mint an installation token and probe read access only). It keeps
the rule but cannot verify `write` permissions without writing, so a missing `checks: write` would only
show up as a 403 on the first PR.

### V-E03 — Workflow permissions

- Generated workflows declare their own minimal `permissions:` blocks, so the repo's default token
  setting does not affect them. The remaining risk is an org policy that restricts Actions, which only an
  admin can read.
- **All modes:** doctor lists the permissions each generated workflow declares (checklist), so the
  platform team knows what to allow.
- **Optional live probe (D7):** with `STAGR_PLATFORM_TOKEN` (admin-level), `--ci` reads the repo's default
  workflow permissions and allowed actions (F6) and reports an ERROR for anything the generated
  workflows need that is blocked. Without the token: `SKIP (no STAGR_PLATFORM_TOKEN)`.

### V-E04 — Trusted roles

- V-S14 already validates role values. Doctor adds an offline check: `WARN` when `trusted_roles` is only
  `owner`, because every PR from anyone else is then skipped.
- **Optional live probe (D7):** with `STAGR_PLATFORM_TOKEN` (push access or better), `--ci` lists
  collaborator roles (F7) and `WARN`s when nobody holds a role in `trusted_roles`. Without the token:
  `SKIP (no STAGR_PLATFORM_TOKEN)`.

## Where the code lives

- Core (`stagr/core/`): the check-result type, the requirements derived from render output, and the
  pass/fail rules. No GitHub knowledge.
- GitHub (`stagr/platforms/github/`): the JWT, the installation call, permission comparison, the
  optional probes, and the declared permissions, behind a small interface so tests inject a fake client (C8).
- CLI (`stagr/cli/`): thin `doctor` command wiring the above.
