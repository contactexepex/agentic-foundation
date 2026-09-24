"""`stagr init` — scaffold a commented .agentic/config.yml, interactively or from a profile."""
from __future__ import annotations

import argparse
import re
import stat
import sys
from pathlib import Path
from typing import Any

import yaml

from .. import render, scaffold
from .report import DEFAULT_CONFIG_PATH

# Shapes of real credentials that must never be serialized into a generated config: GitHub tokens
# (ghp_/gho_/ghu_/ghs_/ghr_/github_pat_) and provider API keys (sk-…, incl. sk-ant-…). A secret
# NAME never looks like these, so matching one means a value was pasted where a NAME was expected.
_SECRET_VALUE_RE = re.compile(r"gh[porsu]_[A-Za-z0-9]{8,}|github_pat_\w{8,}|sk-[A-Za-z0-9-]{8,}")


_REPARSE_POINT_ATTR = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


def _is_reparse_point(path: Path) -> bool:
    """True if `path` is a Windows reparse point — a symlink OR an NTFS directory junction.

    `Path.is_symlink()` does not flag junctions, so a junctioned ancestor could still redirect the
    write on Windows. The reparse-point flag (exposed only on Windows via lstat's
    `st_file_attributes`) catches both symlinks and junctions. On POSIX that attribute is absent, so
    this returns False and `is_symlink()` alone does the work — the check is inert off Windows.
    """
    try:
        return bool(path.lstat().st_file_attributes & _REPARSE_POINT_ATTR)
    except (AttributeError, OSError, ValueError):
        return False


def _symlink_in_chain(dest: Path) -> Path | None:
    """First symlink/junction in `dest`'s chain, checking EVERY component, or None if there is none.

    Walks the destination from the leaf to the filesystem root, testing each component with
    `is_symlink()` (and, on Windows, the reparse-point flag) — an lstat of that single component
    that does not follow it. Any symlink or junction is rejected: the leaf itself (so even a broken
    link is caught) OR an ancestor such as a crafted `.agentic` -> outside in an untrusted checkout,
    which `mkdir`/`write_text` would follow to escape the repo. Every component is inspected — there
    is no early exists()/is_dir() boundary, because those follow symlinks in earlier components and
    could skip a symlinked ancestor.

    The absolute path is built by joining onto the (already symlink-free) cwd WITHOUT normalizing
    `..`. `os.path.abspath`/`normpath` would collapse `link/../x` to `x` lexically, hiding the
    `link` symlink the filesystem actually follows; Path joining and Path.parent are purely
    lexical, so a symlinked component that precedes a `..` is still visited and rejected.
    """
    cur = dest if dest.is_absolute() else Path.cwd() / dest
    while True:
        if cur.is_symlink() or _is_reparse_point(cur):
            return cur
        parent = cur.parent
        if parent == cur:  # reached the filesystem anchor
            return None
        cur = parent


def _emit_to_stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _prompt_from_stdin(prompt: str) -> str:
    # Write the prompt to STDERR (not stdout) and read the answer from stdin, so the wizard's UI
    # never lands on stdout. This keeps `stagr init --print > .agentic/config.yml` (interactive
    # stdin, redirected stdout) producing a file that is pure YAML.
    sys.stderr.write(prompt)
    sys.stderr.flush()
    return sys.stdin.readline()


def _resolve_init_choices(args: argparse.Namespace) -> dict[str, Any] | None:
    """Pick the wizard/profile answers for `init`.

    Returns the choices, or None when setup cannot proceed (a `--profile` value the scaffold
    rejects, or a non-interactive run with no `--profile`); the reason is printed to stderr.
    """
    if args.profile or args.yes:
        try:
            choices = scaffold.default_choices(args.profile or "standard")
        except ValueError as exc:
            print(f"init: {exc}", file=sys.stderr)
            return None
        # Propose the repo's autodetected build toolchain instead of the blind default (the wizard
        # does the same for its interactive default). Still written as an overridable value.
        choices["build_preset"] = scaffold.detect_build_preset()
        return choices
    if sys.stdin.isatty():
        # The wizard is UI: route every prompt and message to stderr so stdout stays reserved for
        # the generated config (`--print`) or the result messages.
        return scaffold.run_wizard(read_input=_prompt_from_stdin, write_line=_emit_to_stderr)
    print(
        "init: not a terminal, and no --profile given.\n"
        "  Run `stagr init` in a terminal for guided setup, or\n"
        "  `stagr init --profile <minimal|standard|full|custom>` to generate a file directly.",
        file=sys.stderr,
    )
    return None


def _generated_config_is_valid(text: str) -> bool:
    """Validate the generated config BEFORE it is printed or written.

    So neither `--print` (which a user may redirect into .agentic/config.yml) nor a write ever
    emits a config that then fails the `doctor`/`plan` step init points at. This catches
    semantically invalid free-form values the schema alone accepts — a secret name with a hyphen,
    a branch with whitespace, a model id with expression metacharacters — which the renderer (the
    single source of truth) rejects. Returns True when valid; otherwise prints why and returns False.
    """
    try:
        generated_cfg = yaml.safe_load(text)
        render.validate_config(generated_cfg)
        render.render_all(generated_cfg, (generated_cfg.get("platform", {}) or {}).get("type", "github"))
    except (render.RenderError, yaml.YAMLError) as exc:
        print(f"init: the chosen values produce a config the pipeline rejects: {exc}\n"
              "  Nothing was written. Re-run and choose values the message above accepts.",
              file=sys.stderr)
        return False
    return True


def _write_generated_config(dest: Path, text: str, force: bool) -> int:
    """Write the generated config to `dest` with symlink/overwrite/IO guards. Returns an exit code."""
    # Refuse to write through a symlink anywhere in the destination's chain — the leaf OR an
    # ancestor (e.g. a crafted `.agentic` symlink in an untrusted checkout would redirect the
    # write outside the repo, and a broken symlink would even slip past the exists() guard).
    # `mkdir`/`write_text` both follow parent symlinks, so guard the whole chain up to the
    # nearest existing real directory (the boundary init writes within).
    linked = _symlink_in_chain(dest)
    if linked is not None:
        which = "" if linked == dest else f" (via ancestor {linked})"
        print(f"init: {dest} is reached through a symlink{which}; refusing to write through it. "
              f"Remove it or pass a different --config path.", file=sys.stderr)
        return 1
    if dest.exists() and not force:
        print(f"init: {dest} already exists — use --force to overwrite, or --print to preview.",
              file=sys.stderr)
        return 1
    # Report a write failure (unwritable location, a file where a parent dir is expected, a
    # directory at the destination) as a concise error and exit 1 — not an uncaught traceback.
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Always UTF-8: the generated file contains em dashes and box-drawing characters that a
        # non-UTF-8 locale encoding (e.g. Windows CP932) cannot represent — a plain write_text would
        # raise UnicodeEncodeError and leave a truncated file.
        dest.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"init: could not write {dest}: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_init_next_steps(dest: Path) -> None:
    """Point the user at the follow-up commands after `init` writes the config."""
    # Follow-up commands default to .agentic/config.yml; when init wrote elsewhere, point the user at
    # the file. Show the path plainly rather than a copy-paste command: shells quote differently
    # (POSIX/PowerShell single quotes vs cmd.exe double quotes), so one quoted command can't be
    # correct everywhere — leave shell-specific quoting to the user.
    if dest == DEFAULT_CONFIG_PATH:
        print("next: `stagr doctor` to validate, `stagr plan` to preview, `stagr apply` to write workflows.")
    else:
        print(f"next: run `stagr doctor`, then `stagr plan`, then `stagr apply`, passing `--config` "
              f"with this file's path to each: {dest}  (quote it for your shell if it has spaces).")


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a commented .agentic/config.yml — interactively, or from a profile."""
    choices = _resolve_init_choices(args)
    if choices is None:
        return 1

    text = scaffold.generate(choices)

    # Never let a real credential reach the file or stdout. If a user pastes a token/key VALUE
    # where a secret NAME is expected (an easy onboarding mistake — `ghp_…`, `github_pat_…`, an
    # `sk-…` API key), it can satisfy the secret-name regex and be serialized. Refuse to emit
    # anything in that case; the value belongs only in the CI secret store, referenced by NAME.
    if _SECRET_VALUE_RE.search(text):
        print("init: an entered value looks like a real credential, not a secret NAME. stagr never\n"
              "  stores secret values — enter the NAME of the secret (its value lives in your CI\n"
              "  secret store). Nothing was written.", file=sys.stderr)
        return 1

    if not _generated_config_is_valid(text):
        return 1

    if args.print_only:
        print(text, end="")
        return 0

    dest = args.config
    # Confine the write destination to the project root, matching the read confinement on
    # doctor/plan/apply. Otherwise init could scaffold a config outside the checkout that those
    # commands then refuse to read, or (with --force) overwrite an arbitrary out-of-repo file.
    try:
        render.confine_config_path(dest)
    except render.RenderError as exc:
        print(f"init: {exc}\n  Nothing was written.", file=sys.stderr)
        return 1
    rc = _write_generated_config(dest, text, args.force)
    if rc != 0:
        return rc
    print(f"init: wrote {dest} (profile: {choices['profile']}).")
    _print_init_next_steps(dest)
    return 0
