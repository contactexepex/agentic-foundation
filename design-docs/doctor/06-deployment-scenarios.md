# Doctor — Deployment Scenarios

Part of the [doctor design set](README.md). Shows how the same doctor fits a solo developer and a large,
regulated organization. These are common patterns, not descriptions of any specific company.

## One mechanism, many setups

Doctor never decides where credentials live. It reads environment variables (04) and the rules in [07](07-credential-safety.md) apply. Each organization
chooses who supplies them and where doctor runs.

## Which checks can run where

| Check | Needs | Pipeline context (repo's own pipeline) | Central context (`--repo`, workflow or laptop) |
|---|---|:-:|:-:|
| V-E01 secrets present | Flags from the repo's `secrets` context, **or** `STAGR_PLATFORM_TOKEN` to list names (D10) | Yes (flags) | Yes (API listing) |
| V-E02a-b App ID, key secret present | Same as V-E01 | Yes | Yes |
| V-E02c-d App installed, permissions | The App key | Yes | **No** (the key is never held centrally or on a laptop) |
| V-E03 workflow permissions (optional) | `STAGR_PLATFORM_TOKEN` | Yes, if the token is present | Yes (`--repo OWNER/NAME`) |
| V-E04 trusted roles (optional) | `STAGR_PLATFORM_TOKEN` | Yes, if the token is present | Yes |

So in a separated setup the **platform team** can check secrets, org settings and roles centrally, and only
the App install and permissions check must run in the **author's pipeline**, because it needs the App key.
A central run prints `not verified: V-E02c, V-E02d` so nobody mistakes it for a full check.

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
- Optional probes (V-E03, V-E04) in the pipeline context: token present but GitHub answers 401, 403 or 404 (too little access, or the endpoint is missing on an
  older Enterprise Server): `SKIP (token lacks access)` with the status code. Not an ERROR.
- In the central context the token is the whole point, so any 401, 403 or 404 is an ERROR ("token lacks
  access"), including the secrets listing.
- Only a positive finding is reported as ERROR or WARN (for example "no collaborator holds a trusted
  role").
- Settings can be enforced at repo, org or enterprise level. The probe reports the effective value it
  saw; the fix line tells the platform team to check the enterprise level too.

## Not in scope

- **Secrets kept outside GitHub** (for example fetched from Vault through OIDC). The generated
  workflows read `${{ secrets.NAME }}`, so V-E01 is correct for what Stagr generates. Vault support
  would be a separate feature.
- **Secrets held only in a GitHub environment.** The generated stage jobs declare no `environment:`, so
  they cannot read these secrets. Doctor does not count them toward V-E01: the secret is reported
  missing, and the fix line says to store it as a repository or organization secret. The doctor job
  declares no environment either, so its presence flags match what the stage sees. Supporting
  environments would mean adding an environment field to the config and the renderer; that is a
  separate feature.
