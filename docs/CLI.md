# `stagr` CLI

`stagr` turns a `.agentic/config.yml` contract into a working pipeline on your repo's CI/SCM. It is a
thin, deterministic layer over the renderer cores (`stagr/core/` for `plan` and `apply`): no network, and **no secret
values are ever read, printed, or logged** — only the secret *names* the contract references.

## What you need

- **Python 3.10 or newer.** Check with `python3 --version` (Linux/macOS) or `py --version` (Windows —
  the launcher, since a default Windows install exposes `py`/`python`, not `python3`). That is the only
  prerequisite — `stagr` is pure Python and its two dependencies (PyYAML, jsonschema) install
  automatically.
- **[pipx](https://pipx.pypa.io)** is the recommended installer: it puts `stagr` on your `PATH` in an
  isolated environment so it never clashes with other Python tools. If you don't have it, bootstrap it,
  add its shims to `PATH`, and open a new terminal:
  ```bash
  # Linux / macOS
  python3 -m pip install --user pipx && python3 -m pipx ensurepath
  # Windows (py launcher)
  py -m pip install --user pipx && py -m pipx ensurepath
  ```
  `ensurepath` is what makes the `pipx` command available in the next shell. Before that PATH entry is
  active you can still invoke it as a module — `python3 -m pipx install …` (or `py -m pipx install …`)
  — which is equivalent to the `pipx …` commands below.

`stagr` runs the same way on **Linux, macOS, and Windows** — one Python package, one command.

## Install

> **Not on PyPI yet.** Until the first release, install from the repository's source archive — pip/pipx
> download and build it with **no `git` required** (so it works on a clean Python-only machine,
> including Windows). For a reproducible, auditable install, pin to an **immutable revision** — a
> commit SHA (or a release tag once one exists); use `main` only for the latest evaluation build:
>
> ```bash
> # reproducible — replace <commit> with a specific commit SHA (or a release tag):
> pipx install "https://github.com/contactexepex/agentic-foundation/archive/<commit>.tar.gz"
> # or the latest tip of main (evaluation only, mutable):
> pipx install "https://github.com/contactexepex/agentic-foundation/archive/refs/heads/main.tar.gz"
> ```
>
> or, from a local checkout of this repository: `pipx install .` (or `pip install .`).

Once published, the standard install will be:

```bash
pipx install stagr        # isolated global command on Linux / macOS / Windows
pip install stagr         # or into the current environment / CI
```

Verify it:

```bash
stagr --help
```

## Use it in your repo

From the root of the repository you want to add the pipeline to (the folder holding — or that will
hold — `.agentic/config.yml`):

```bash
stagr <init|doctor|plan|apply> [options]
```

The usual order is **init → doctor → plan → apply**.

### `stagr init`

Create a starter `.agentic/config.yml` so you never hand-write YAML from scratch. Two ways:

- **Guided (default):** `stagr init` runs a short wizard — grouped questions (platform, model, build
  checks, governance), each showing the **available options and the default**; press **Enter** to
  accept a default and complete onboarding without looking anything up.
- **Generate from a profile:** `stagr init --profile <minimal|standard|full|custom>` writes a
  **commented** config directly (no prompts) — every section explains its purpose, default, and use.
  This is also the non-interactive / CI path.

Either way, `init` **autodetects your build toolchain** from marker files in the repo and proposes the
matching `build.preset` as the default (the wizard pre-selects it; `--profile` generation uses it).
Detection is **conservative**: it picks a preset only when the repo has the marker that preset's
commands actually need, so a proposed preset always renders a Validate workflow that can run —
`requirements.txt` → `python`, `pom.xml` → `maven`, `gradlew` → `gradle`, `package-lock.json`/
`npm-shrinkwrap.json` → `node`, `go.mod` → `go`, `Cargo.toml` → `rust`, `*.csproj`/`*.sln` → `dotnet`.
Anything else — including a `package.json` with no lockfile or a `pyproject`-only project — proposes
`custom` (you fill in the commands) rather than a preset whose commands would fail. Detection reads
only these top-level filenames (offline, no file contents), and the value stays overridable. A preset determines the install/lint/test
commands the rendered Validate workflow runs (see [CONFIGURATION.md §4 Presets](CONFIGURATION.md#4-presets));
preview the exact rendered commands with `python -m stagr.render --print`, and override any that don't fit by setting them under `build.commands` in the config.

```bash
stagr init                      # guided wizard
stagr init --profile standard   # generate a commented standard config
stagr init --profile minimal --print   # preview to stdout, write nothing
```

Profiles size the file: **minimal** (implement + review), **standard** (+ security review),
**full** (+ the roadmap stages, commented), **custom** (a skeleton you fill in). It is
non-destructive — it won't overwrite an existing config without `--force`.

### `stagr doctor`

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
stagr doctor --config .agentic/config.yml
stagr doctor --json        # for CI health checks
```

### `stagr plan`

Dry run: check the contract and show exactly what `apply` **would** write. It runs the same
pipeline as `apply` (static validation V-S01 to V-S12, normalization, then the stage, routing and
governance renderers), so a config that passes `plan` will not fail `apply` on validation or
rendering grounds (`apply` can still fail on filesystem errors). It writes **nothing** to your
repository: the workflows are rendered in a private temporary directory that is deleted afterwards.

For each artifact it prints the file name, its size, its SHA-256 hash, and whether it is `new`,
`changed`, or `unchanged` compared with the target directory. The hashes are exactly those of the
files `apply` writes. Stage workflows that an earlier run wrote but this config no longer renders
are listed as stale (hand-written workflows are never mentioned). Warnings (for example V-S11,
routing keys kept while `fast_path` is disabled) go to stderr and do not change the exit code.

Exit code `0` on success, `1` on any error (the message names the failed check).

```bash
stagr plan                 # summary against .github/workflows/
stagr plan --diff          # unified diff for changed workflows
stagr plan --out some/dir  # compare against a different target directory
```

### `stagr apply`

Validate, render, and write the workflows to `.github/workflows/` (override with `--out`). Nothing
is written unless every check and every stage renders successfully. For each enabled stage it
writes `stage-<stage id>.yml`; it also writes `routing.yml` and `governance.yml`. Running it twice
gives the same files: only files whose content changed are written, and each file is replaced
atomically.

`apply` never touches files it did not generate. A `stage-*.yml` file that this config no longer
renders (for example after you removed a stage) is kept and reported; pass `--prune` to delete
those stale stage workflows. Hand-written workflows such as `ci.yml` are never deleted, even with
`--prune`.

`apply` and `plan` need the Stagr GitHub App that publishes Stagr's Check Runs. Set its numeric ID
in the config (the ID is public, not a secret). The private key lives in a repository secret; only
its name goes in the config, and it defaults to `STAGR_APP_PRIVATE_KEY`:

```yaml
platform:
  publisher:
    app_id: 123456                          # your Stagr GitHub App ID
    # private_key_secret: STAGR_APP_PRIVATE_KEY   # optional; this is the default
```

Without `platform.publisher` both commands stop with an error that says so.

> **What renders today:** one `stage-<id>.yml` per enabled stage (Claude Code implementer and Codex
> review/security stages), the `routing.yml` path-classification workflow, and the `governance.yml`
> merge gate. `plan` and `apply` do not render the older Validate, review-router, Codex thread
> cleanup or `auto-merge.yml` workflows; `stagr doctor` and `python -m stagr.render` still use that
> older renderer until they move to the same pipeline. Stage types other than the ones above, and
> `from:` agent presets, are not supported by this pipeline yet. Run `plan` first: it lists the
> exact files `apply` will write.

```bash
stagr apply                # write/update the rendered pipeline
stagr apply --prune        # also remove stage workflows this config no longer renders
```

### `stagr help`

Discover commands without leaving the terminal:

```bash
stagr help          # list every command with its purpose
stagr help init     # detail for one command (also: `stagr init help`)
```

## Safety model

- **Secrets by name only.** The CLI reads the config, which references secrets by name; it never
  reads the environment for a secret value and never prints one. `doctor` output is safe to paste
  into an issue or CI log.
- **Fail-loud.** An unresolvable model, an invalid schema, an unsupported contract shape (e.g. a
  `uri` skill source or `extends` base offline), or a missing selected template stops the command
  with a precise error rather than emitting a broken pipeline.
- **All or nothing.** `plan` and `apply` validate and render everything before the first file is
  written, so an error in any stage leaves your workflows untouched.
- **Non-destructive by default.** `apply` adds and updates only the files it generates; it deletes
  only stale `stage-*.yml` files, and only with `--prune`. It refuses to replace a symlink or a
  directory with a workflow file.

## Build the package (maintainers)

The CLI and its data (schema + `templates/`) live in the `stagr/` package, so a standard build ships
everything needed:

```bash
pip install build
python -m build            # writes dist/stagr-<version>-py3-none-any.whl and .tar.gz
pipx install dist/stagr-*.whl   # smoke-test the built wheel
```

The single wheel is what every install path uses (`pipx`, `pip`, and — later — any OS package that
wraps it). The project is licensed (Business Source License 1.1); publishing to PyPI is a future
step — reserve the `stagr` name and run `twine upload dist/*`.
