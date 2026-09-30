# Doctor — Roles and Setup Flow

Part of the [doctor design set](README.md). Stagr should make the platform team's and config author's
work easy: do the deriving, say exactly what is needed, and name who does it.

## Roles

| Role | Who | Has | Does not have |
|---|---|---|---|
| **Config author** | A developer or platform engineer setting up a repo | Write access to the repo | Admin rights, the App private key |
| **Platform team** | The central CI / GitHub administrators | Org/repo admin, the App, the secrets | — |
| **Maintainer** | Repo owners who review and merge | Merge rights | — |
| **Stagr** | The CLI | Only what its environment gives it | Any ability to create or change GitHub settings |

## Who does what

| Task | Config author | Platform team | Maintainer |
|---|:-:|:-:|:-:|
| Create the Stagr GitHub App (once per org) | | **Do** | |
| Install the App on the repo | | **Do** | |
| Store the App private key and provider secrets | | **Do** | |
| Write `.agentic/config.yml` and skills | **Do** | | Review |
| Run `stagr plan`, `apply`, `doctor` locally | **Do** | | |
| Hand the provisioning checklist to the platform team | **Do** | Receive | |
| Add the `stagr doctor --ci` step to the pipeline | **Do** | Review | |
| Fix a doctor ERROR | As the message says | As the message says | |
| Merge the PR | | | **Do** |

Every doctor ERROR and checklist line names the role that fixes it (for example "Ask the platform team
to install App 123456 on this repository").

## First-time setup flow (new or existing repo)

1. **Config author** writes `.agentic/config.yml` locally.
2. `stagr plan`, then `stagr apply`: validate and generate the workflows.
3. `stagr doctor` (local): static validation passes, every live check is `SKIP`, and the
   **provisioning checklist** prints.
4. The author sends the checklist to the **platform team**. It lists the secret names, App ID and App
   permissions this config needs, so nobody guesses.
5. **Platform team** provisions: installs the App, stores the secrets, grants the permissions.
6. The author opens a PR with the config, the generated workflows, and a pipeline step running
   `stagr doctor --ci` on a trusted trigger (see 04).
7. `--ci` runs with real credentials. Green means the environment matches the config. An ERROR names
   what is missing and who fixes it.
8. **Maintainer** merges.

Steps 5 and 7 are the only ones that need privileged access, and neither is done by the author.

## Ongoing use

Adding a stage or provider changes the required secrets and permissions. Re-running local
`stagr doctor` prints the updated checklist; the platform team acts on the difference.
