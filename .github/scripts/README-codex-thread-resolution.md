# Codex review-thread auto-resolution

The `Resolve Fixed Codex Review Threads` workflow runs for every pull request — on open, reopen,
push (`synchronize`), and base-retarget onto the default branch — and resolves a review thread only
when all of these conditions hold:

- the PR head is a same-repository branch whose base is the default branch;
- GitHub marks the review thread as outdated after a later commit changed the code;
- the thread is still unresolved; and
- every comment in the thread was authored by the `chatgpt-codex-connector` GitHub App.

Human-authored and mixed human/bot review threads are never resolved automatically. Resolution runs
independently of the validation workflow, so it also covers pull requests that touch only workflows
or documentation. Thread resolution does not gate merges — CI (the `Validate` check) and Codex's own
re-review still decide mergeability. A run is ignored if the PR head has moved since its event fired.

## Known limitation

GitHub marks a thread `isOutdated` when the anchored code changes at all — not only when the finding
is actually fixed. So a cosmetic edit (reformat, comment) to a flagged line can mark a genuine Codex
finding outdated and auto-resolve it. This is backstopped by the re-review requested on every push
(`request-codex-review-on-push.yml`): a still-valid issue is re-flagged as a new thread and re-blocks
the auto-merge gate. Do not rely on auto-resolution to clear a real finding — address it in code.
