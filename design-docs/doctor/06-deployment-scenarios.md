# Doctor — Deployment Scenarios

Part of the [doctor design set](README.md). Shows how the same doctor fits a solo developer and a large,
regulated organization. These are common patterns, not descriptions of any specific company.

## One mechanism, many setups

Doctor never decides where credentials live. It reads environment variables (04). Each organization
chooses who supplies them and where doctor runs.

## Which checks can run where

| Check | Needs | Can run in the repo's own pipeline | Can run in a central platform workflow |
|---|---|:-:|:-:|
| V-E01 secrets present | The repo's own `secrets` context | Yes | **No** (a central workflow sees only its own secrets) |
| V-E02 App key, install, permissions | The repo's secrets and the App key | Yes | **No** (same reason) |
| V-E03 workflow permissions (optional) | `STAGR_PLATFORM_TOKEN` | Yes, if the token is present | Yes (set `GITHUB_REPOSITORY` per target repo) |
| V-E04 trusted roles (optional) | `STAGR_PLATFORM_TOKEN` | Yes, if the token is present | Yes |

So in a separated setup the split is natural: the **author's pipeline** checks secrets and the App; the
**platform team** checks org and role settings.

## Scenarios

| # | Scenario | Token holder | Who runs the optional probes |
|---|---|---|---|
| 1 | **Solo or small team**: the same people write the config and own the repo settings | Stored as a repo secret, or skip the probes | The repo's own pipeline, every run |
| 2 | **Mid-size company with a platform team** | Platform team | Platform team in a workflow they own; the author's pipeline shows `SKIP` |
| 3 | **Large corporation, hundreds of repos** | Central platform or security team | One central workflow, a matrix over target repos. No long-lived admin token is stored in any product repo |
| 4 | **Regulated (bank, airline)**: personal tokens restricted or approval-gated, audited access | A short-lived token minted just in time from an App, used only on the platform team's runners | Platform team, or not at all. The provisioning checklist is then the control |
| 5 | **GitHub Enterprise Server or several orgs** | As above, per instance | As above. `GITHUB_API_URL` selects the instance; endpoints can differ by version |

## Token guidance for the platform token

Doctor accepts any token that has enough access. In order of preference:

1. **A dedicated read-only GitHub App** installed by the platform team. The installation token expires
   after an hour and is not tied to a person. It suits scenarios 3 to 5.
2. **A fine-grained personal token** with the minimum read access. Many organizations require an owner to
   approve each one, or restrict them.
3. **A classic personal token.** Last resort; its scopes are broad.

The exact minimum permissions for V-E03 and V-E04 must be confirmed (F6, F7 in
[01](01-constraints.md)) and are then written into `docs/CLI.md`.

## Failure rules for the optional probes

- No token: `SKIP (no STAGR_PLATFORM_TOKEN)`.
- Token present but GitHub answers 401, 403 or 404 (too little access, or the endpoint is missing on an
  older Enterprise Server): `SKIP (token lacks access)` with the status code. Not an ERROR.
- Only a positive finding is reported as ERROR or WARN (for example "no collaborator holds a trusted
  role").
- Settings can be enforced at repo, org or enterprise level. The probe reports the effective value it
  saw; the fix line tells the platform team to check the enterprise level too.

## Not in scope

- **Secrets kept outside GitHub** (for example fetched from Vault through OIDC). The generated
  workflows read `${{ secrets.NAME }}`, so V-E01 is correct for what Stagr generates. Vault support
  would be a separate feature.
- **Central secret-name listing.** A platform token could list a repo's secret names through the API so
  V-E01 can also run centrally. Deferred; revisit if a real need appears.
- **Secrets held in a GitHub environment.** The doctor job must declare that environment to see them,
  and may then wait for its approval rules. Note this in the runbook; no special support.
