# `agentic` CLI (M3)

The operator CLI turns a `.agentic/config.yml` contract into a working pipeline. It is a thin,
deterministic layer over the M2 renderer core (`install/render.py`): no network, and **no secret
values are ever read, printed, or logged** — only the secret *names* the contract references.

```bash
python install/cli.py <doctor|plan|apply> [--config .agentic/config.yml] [--platform github]
```

(Once packaged, this is exposed as the `agentic` command; the examples below use that name.)

## `agentic doctor`

Validate the contract and resolve the stage graph, then print a health report:

- profile, platform, default branch, trusted roles, and enabled modules;
- every stage with its `type`, `backend`, and **resolved model** (or `(app-supplied by backend …)`
  for app backends such as `codex`, which choose their own model);
- the **secret NAMES** the pipeline needs (provider API keys, any `extra_headers_secret`, and the
  codex review PAT) — configure these in your CI secret store; their values never appear here;
- the workflow files that would be rendered.

Exits non-zero if the config is invalid or any required model cannot be resolved (fail-loud — no
hidden default). `--json` emits the report as machine-readable JSON for CI.

```bash
agentic doctor --config .agentic/config.yml
agentic doctor --json        # for CI health checks
```

## `agentic plan`

Dry run: show exactly what `apply` **would** write to `.github/workflows/`, marking each workflow
`new`, `changed`, or `unchanged`, and listing any hand-written workflows the config does not render
(left untouched). Writes nothing.

```bash
agentic plan                 # summary against .github/workflows/
agentic plan --diff          # unified diff for changed workflows
agentic plan --out some/dir  # compare against a different target
```

## `agentic apply`

Render the pipeline and write it to `.github/workflows/` (override with `--out`). Idempotent — only
files whose content changed are written. By default it never deletes: a workflow present in the
target that this config does not render is kept and reported. Pass `--prune` to remove such orphans.

```bash
agentic apply                # write/update the rendered pipeline
agentic apply --prune        # also remove workflows this config no longer renders
```

## Safety model

- **Secrets by name only.** The CLI reads the config, which references secrets by name; it never
  reads the environment for a secret value and never prints one. `doctor` output is safe to paste
  into an issue or CI log.
- **Fail-loud.** An unresolvable model, an invalid schema, an unsupported contract shape (e.g. a
  `uri` skill source or `extends` base offline), or a missing selected template stops the command
  with a precise error rather than emitting a broken pipeline.
- **Non-destructive by default.** `apply` adds and updates; it deletes only with `--prune`.
