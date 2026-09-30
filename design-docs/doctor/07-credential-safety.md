# Doctor — Credential Safety

Part of the [doctor design set](README.md). Rules for any context where doctor holds a credential,
including a platform engineer running a central check from a laptop. Constraints are in
[01](01-constraints.md); contexts are in [04](04-cli-and-output.md).

## What a laptop can and cannot do

| Goal | Allowed | How |
|---|---|---|
| Check secret names, workflow permissions and trusted roles with an elevated token | **Yes** | `STAGR_PLATFORM_TOKEN=... stagr doctor --repo OWNER/NAME` (central context) |
| Check App install and permissions (V-E02c-d) | **No** | Needs the App private key, which never belongs on a laptop. Reported as `not verified`; runs in the repo pipeline |
| Trigger the real pipeline or change any setting | **Never by doctor** | Doctor is read-only (C6). A person with rights runs the pipeline's own doctor step, for example a manual trigger |

## Rules

1. **Explicit opt-in only.** Doctor reads `STAGR_PLATFORM_TOKEN` and no other credential. It never uses a
   `gh` login, `GITHUB_TOKEN`, or any ambient credential, because those are often far broader than the
   operator intends.
2. **Read-only by construction.** The API client permits only GET requests. A test enforces this.
3. **The token goes to one place.** It is sent only to the GitHub API host from `GITHUB_API_URL` (default
   `https://api.github.com`), over HTTPS. The config file cannot set the host, the token, or the target
   repo, so a malicious `.agentic/config.yml` from a PR branch cannot redirect a credential.
4. **Never printed or logged.** Output says a token is in use and which repo it targets, never the value.
   A test checks that a sentinel token never appears in stdout or stderr.
5. **No App private key outside the pipeline context.** `STAGR_DOCTOR_APP_KEY` is read only when
   `GITHUB_ACTIONS=true` and no `--repo` is given. Anywhere else doctor ignores it and prints a warning.
   In the pipeline it is used only to sign a short-lived JWT in memory (D3) on trusted triggers.
6. **Prefer short-lived tokens.** The docs recommend an expiring token, such as a read-only GitHub App
   installation token (about an hour), over a long-lived personal token, especially on laptops.

## What these rules do not cover

A compromised laptop, or a token left in shell history, is outside doctor's control. The runbook says so
and points to rule 6.

## Where it lives in the code

The API client, its GET-only guard, host validation and token redaction are in one small GitHub-platform
module, so every probe goes through the same checked path (C8).
