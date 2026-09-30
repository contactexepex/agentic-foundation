# Doctor — CLI and Output

Part of the [doctor design set](README.md). Checks are defined in [03](03-validation-design.md).

## Commands

```
stagr doctor [--root PATH]          # local: offline, no credentials
stagr doctor --ci [--root PATH] [--repo OWNER/NAME]   # CI: live checks, expects the inputs below
```

`--root` matches `plan` and `apply`. `--repo` defaults to `GITHUB_REPOSITORY`. A central workflow passes it
per target repo, because the default `GITHUB_*` variables cannot be overwritten (F9). There is no `--strict` or `--json`; add them only when a real need
appears.

## `--ci` inputs

| Input | Source | Purpose |
|---|---|---|
| `STAGR_HAS_<SECRET_NAME>` = `true`/`false` | workflow: `${{ secrets.NAME != '' }}` | V-E01, V-E02 key present. Flag only, never the value |
| `STAGR_DOCTOR_APP_KEY` | workflow: `${{ secrets.<private_key_secret> }}` | V-E02 JWT (D3) |
| `STAGR_PLATFORM_TOKEN` (optional) | workflow: `${{ secrets.STAGR_PLATFORM_TOKEN }}` | V-E03 and V-E04 live probes. Absent or lacking access: they `SKIP`. Where it comes from: [06](06-deployment-scenarios.md) |
| `GITHUB_REPOSITORY`, `GITHUB_API_URL` | provided by Actions; `--repo` overrides the repo for a central run | which repo and GitHub instance to query |

**Which source answers V-E01 and V-E02b (D10):**

| Inputs present | Source | Use |
|---|---|---|
| At least one `STAGR_HAS_*` flag | Flags | Repo pipeline. A required flag that is missing is an ERROR naming it. The App key is required |
| No flags, `STAGR_PLATFORM_TOKEN` set | Secrets API | Central run. V-E02c/d are `SKIP` (need the App key) |
| Neither | none | ERROR: no presence flags and no platform token |

So `STAGR_PLATFORM_TOKEN` is optional in the repo pipeline (it only enables V-E03/V-E04) and required in a
central run. Every V-E01 and V-E02b line prints its source (`flags` or `API`), and a central run ends with
`not verified: V-E02c, V-E02d`, so a skipped App check is never silent.

## Output

One line per check: `[STATUS] V-Exx: short title`, then an indented reason and a fix line naming the role.

Local:

```
stagr doctor (local mode: live checks are SKIPPED; run `stagr doctor --ci` in your pipeline)
[PASS] static validation
[SKIP] V-E01: backend secrets        cannot verify locally; see checklist
[PASS] V-E02a: App ID configured     123456
[SKIP] V-E02b-d: App credentials     cannot verify locally; see checklist
[SKIP] V-E03: workflow permissions   cannot verify locally; see checklist
[WARN] V-E04: trusted roles          only `owner`: PRs from everyone else are skipped
```

`--ci` failure:

```
[ERROR] V-E01: backend secrets
        missing REMEDIATION_TOKEN (needed by stage `review`)
        fix: platform team adds repository secret REMEDIATION_TOKEN
[ERROR] V-E02c: App installed
        App 123456 is not installed on acme/widgets
        fix: platform team installs the App on this repository
```

Doctor ends with a one-line summary and exits `0` with no ERROR, `1` otherwise. Output is labeled as
environment-dependent: a local `SKIP` is expected, and only `--ci` is authoritative.

## Provisioning checklist (printed in local mode)

Plain text the author can paste into a ticket, derived from the requirements:

```
Provisioning checklist for acme/widgets  (hand to your platform team)
Secrets (names only):      ANTHROPIC_API_KEY (stage review), STAGR_APP_PRIVATE_KEY (App key)
Stagr GitHub App:          ID 123456, installed on this repository
App permissions:           checks: write, pull_requests: read, issues: read
Workflow permissions:      <per workflow, as declared>
Trusted roles:             owner, member, collaborator
```

Followed by a **CI step snippet** for this exact config: a job with the `STAGR_HAS_*` flags and the key
env already filled in, on a trusted trigger. The snippet is generated from the same
requirements, so it cannot drift.

## Docs that teach this

`docs/CLI.md` gets a setup runbook organized by role (02), and its "No network" rule becomes "no network
except `doctor --ci`". Both ship with the implementation. The exact CI snippet is **not** duplicated in the
docs (D8): the docs explain the flags and point to `stagr doctor`, so there is one source of truth.
