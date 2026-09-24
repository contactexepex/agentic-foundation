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
