# `stagr` CLI

`stagr` is the command line of the agentic-foundation control plane. It is a thin, deterministic layer
over the neutral core (`stagr/core/`): no network, and **no secret values are ever read, printed, or
logged** — only the secret *names* the contract references.

**Today the only command is `stagr help`.** The commands that turn a `.agentic/config.yml` into a
pipeline (`plan`, `apply`, `init`, `doctor`) are planned; see [Planned commands](#planned-commands).

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
stagr help
```

## Commands

### `stagr help`

Discover commands without leaving the terminal:

```bash
stagr help          # list every command with its purpose
stagr help <command>  # detail for one command (also: `stagr <command> help`)
```

## Planned commands

These do not exist yet. They are described here so the design is visible; do not rely on them.

- **`stagr plan`** — dry run: list the files the config would produce, and write nothing.
- **`stagr apply`** — write those same files to `.github/workflows/`.
- **`stagr init`** — create a starter `.agentic/config.yml`. It will ask for the GitHub App ID of the
  Stagr publisher App.
- **`stagr doctor`** — validate the config and list the secret **names** the pipeline needs.

Renderers only return the files they would produce and never write them; `plan` lists that result and
`apply` writes it, so what `plan` shows is what `apply` writes. Cleaning up stale files will be
designed as its own step.

## Design rules

- **No network.** The CLI never calls out.
- **Secrets by name only.** The CLI reads the config, which references secrets by name; it never
  reads the environment for a secret value and never prints one.
- **Fail loud.** An invalid config or an unsupported contract shape stops the command with a precise
  error rather than producing a broken pipeline.

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
