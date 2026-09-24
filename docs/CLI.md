# `stagr` CLI

`stagr` turns a `.agentic/config.yml` contract into a working pipeline on your repo's CI/SCM. It is a
thin, deterministic layer over the renderer core (`stagr/render.py`): no network, and **no secret
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
preview the exact rendered commands with `python -m stagr.render --print` (or run `stagr apply` and read
`.github/workflows/`), and override any that don't fit by setting them under `build.commands` in the config.

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

Dry run: show exactly what `apply` **would** write to `.github/workflows/`, marking each workflow
`new`, `changed`, or `unchanged`, and listing any hand-written workflows the config does not render
(left untouched). Writes nothing.

```bash
stagr plan                 # summary against .github/workflows/
stagr plan --diff          # unified diff for changed workflows
stagr plan --out some/dir  # compare against a different target
```

### `stagr apply`

Render the pipeline and write it to `.github/workflows/` (override with `--out`). Idempotent — only
files whose content changed are written. By default it never deletes: a workflow present in the
target that this config does not render is kept and reported. Pass `--prune` to remove such orphans.

> **What renders today:** the core lane — the `Validate` check, the review router, the Claude
> implementer, and (when a Codex review/security stage is configured) the Codex review + thread-cleanup
> lane. **Not yet rendered:** other stage types (`plan`, `test`, `integration-test`, `docs`, `release`,
> and non-Codex reviewers) **and the `modules` toggles** (`auto_merge`, `sonar`) — declared and
> validated but they do not yet emit workflows; multi-stage rendering is roadmap
> ([CHARTER.md](CHARTER.md) §7). Run `plan` first: it lists the exact files `apply` will write, so a
> declared stage or module that does not yet render is visible before you commit.

```bash
stagr apply                # write/update the rendered pipeline
stagr apply --prune        # also remove workflows this config no longer renders
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
- **Non-destructive by default.** `apply` adds and updates; it deletes only with `--prune`.

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
