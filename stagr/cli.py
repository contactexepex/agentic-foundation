#!/usr/bin/env python3
"""stagr — the agentic-foundation control plane CLI.

Subcommands over the renderer core (`render.py`), so newcomers can adopt the toolkit with one
command and experts can inspect exactly what it will do first:

    stagr init     # scaffold a commented .agentic/config.yml (guided wizard, or --profile to generate)
    stagr doctor   # validate config + resolve the graph; report health, secrets (by NAME), lanes
    stagr plan     # dry run: show what apply WOULD write to .github/workflows (no writes)
    stagr apply    # render the pipeline and write it (idempotent; never deletes unless --prune)
    stagr help     # list commands, or `stagr help <command>` / `stagr <command> help` for detail

Design invariants (shared with the renderer):
  * No network. No secret VALUES are ever read, printed, or logged — only the secret NAMES
    the contract references, so an operator knows what to configure.
  * Fail loud: a config that does not resolve (schema, semantics, or an unresolvable model)
    exits non-zero with a precise message rather than emitting a broken pipeline.
  * Deterministic and idempotent: apply writes only files whose content changed.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import shlex
import stat
import sys
from pathlib import Path
from typing import Any

import yaml

from . import render, scaffold
from .backends.generic.runner import DEFAULT_KEY_SECRET

# Shapes of real credentials that must never be serialized into a generated config: GitHub tokens
# (ghp_/gho_/ghu_/ghs_/ghr_/github_pat_) and provider API keys (sk-…, incl. sk-ant-…). A secret
# NAME never looks like these, so matching one means a value was pasted where a NAME was expected.
_SECRET_VALUE_RE = re.compile(r"gh[porsu]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|sk-[A-Za-z0-9-]{8,}")


# --------------------------------------------------------------------------- helpers


def _stage_provider(cfg: dict[str, Any], stage: dict[str, Any]) -> str | None:
    return stage.get("provider") or (cfg.get("defaults", {}) or {}).get("provider")


def _key_secret_name(cfg: dict[str, Any], provider: str) -> str:
    providers = cfg.get("providers", {}) or {}
    return (providers.get(provider, {}) or {}).get(
        "api_key_secret", DEFAULT_KEY_SECRET.get(provider, "MODEL_API_KEY")
    )


def collect_report(cfg: dict[str, Any], platform: str) -> dict[str, Any]:
    """Resolve the config into a structured, secret-free health report.

    Returns model resolution per stage (or the reason it is app-supplied / unresolved),
    the set of secret NAMES the pipeline needs, the enabled modules, and the workflow
    files that would be rendered. Never contains a secret value.
    """
    stages = render.expand_stages(cfg)
    plat = cfg.get("platform", {}) or {}
    report: dict[str, Any] = {
        "profile": cfg.get("profile", "standard"),
        "platform": platform,
        "default_branch": plat.get("default_branch", "main"),
        "trusted_roles": plat.get("trusted_roles", ["owner", "member", "collaborator"]),
        "modules": cfg.get("modules", {}) or {},
        "stages": [],
        "secret_names": [],
        "workflows": [],
        "problems": [],
    }

    secret_names: set[str] = set()
    for stage in stages:
        backend = render._stage_backend(stage)
        provider = _stage_provider(cfg, stage)
        entry: dict[str, Any] = {
            "id": stage.get("id"),
            "type": stage.get("type", "custom"),
            "backend": backend,
            "provider": provider,
            "gate": stage.get("gate"),
            "skill": stage.get("skill"),
        }
        # Resolve the model only for backends that consume one; app backends supply their own.
        if backend in render.BACKENDS_NEEDING_MODEL:
            try:
                entry["model"] = render.resolve_model(cfg, stage, "standard")
            except render.RenderError as exc:
                entry["model"] = None
                report["problems"].append(f"stage '{stage.get('id')}': {exc}")
        else:
            entry["model"] = f"(app-supplied by backend '{backend}')"
        # Record the provider API-key NAME (never a value) ONLY for backends that consume a model
        # key. App backends (e.g. codex) drive their own model via their GitHub App and never read
        # the provider key, so reporting it would tell the operator to create an unused credential.
        if provider and backend in render.BACKENDS_NEEDING_MODEL:
            secret_names.add(_key_secret_name(cfg, provider))
            extra = ((cfg.get("providers", {}) or {}).get(provider, {}) or {}).get("extra_headers_secret")
            if extra:
                secret_names.add(extra)
        report["stages"].append(entry)

    # The codex review lane authors comments/resolutions with a real-user PAT (NAME only).
    if any(stage.get("type") in render.REVIEW_LANE_TYPES and render._stage_backend(stage) == render.BACKEND_CODEX
           for stage in stages):
        secret_names.add(((plat.get("auth", {}) or {}).get("token_secret")) or render.DEFAULT_TOKEN_SECRET)

    report["secret_names"] = sorted(secret_names)
    try:
        report["workflows"] = sorted(render.render_all(cfg, platform).keys())
    except render.RenderError as exc:
        report["problems"].append(f"render: {exc}")
    return report


def _load_validated(config_path: Path) -> tuple[dict[str, Any], str]:
    cfg = render.load_config(config_path)
    render.validate_config(cfg)
    platform = (cfg.get("platform", {}) or {}).get("type", "github")
    return cfg, platform


# --------------------------------------------------------------------------- doctor


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        cfg, platform = _load_validated(args.config)
    except render.RenderError as exc:
        print(f"doctor: config is invalid: {exc}", file=sys.stderr)
        return 1
    platform = args.platform or platform
    report = collect_report(cfg, platform)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if report["problems"] else 0

    print(f"stagr doctor — {args.config}")
    print(f"  profile:        {report['profile']}")
    print(f"  platform:       {report['platform']} (default branch: {report['default_branch']})")
    print(f"  trusted roles:  {', '.join(report['trusted_roles'])}")
    module_summary = ", ".join(f"{name}={value}" for name, value in report["modules"].items()) or "(none)"
    print(f"  modules:        {module_summary}")
    print("  stages:")
    for stage in report["stages"]:
        print(
            f"    - {stage['id']:<16} type={stage['type']:<16} backend={stage['backend']:<16} "
            f"model={stage['model']}"
        )
    print("  secrets required (configure these NAMES; values live in CI secrets, never here):")
    for name in report["secret_names"]:
        print(f"    - {name}")
    print(f"  workflows to render: {', '.join(report['workflows']) or '(none)'}")

    if report["problems"]:
        print("\ndoctor: problems found:", file=sys.stderr)
        for problem in report["problems"]:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\ndoctor: healthy — config resolves and the pipeline renders.")
    return 0


# ----------------------------------------------------------------------- plan / apply


def _render_or_fail(config_path: Path, platform_override: str | None) -> dict[str, str]:
    cfg, platform = _load_validated(config_path)
    return render.render_all(cfg, platform_override or platform)


def _classify(out_dir: Path, rendered: dict[str, str]) -> list[tuple[str, str]]:
    """Compare rendered output against the target dir: (status, name) per workflow."""
    result: list[tuple[str, str]] = []
    for name, content in sorted(rendered.items()):
        target = out_dir / name
        if not target.exists():
            result.append(("new", name))
        elif target.read_text() == content:
            result.append(("unchanged", name))
        else:
            result.append(("changed", name))
    return result


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        rendered = _render_or_fail(args.config, args.platform)
    except render.RenderError as exc:
        print(f"plan: {exc}", file=sys.stderr)
        return 1
    out_dir = args.out
    print(f"stagr plan — would render {len(rendered)} workflow(s) into {out_dir}/")
    for status, name in _classify(out_dir, rendered):
        marker = {"new": "+ new     ", "changed": "~ changed ", "unchanged": "= unchanged"}[status]
        print(f"  {marker} {name}")
        if status == "changed" and args.diff:
            current = (out_dir / name).read_text().splitlines()
            new = rendered[name].splitlines()
            for line in difflib.unified_diff(current, new, fromfile=f"a/{name}", tofile=f"b/{name}", lineterm=""):
                print(f"      {line}")
    # Orphans: workflow files present in the target that this config would NOT render.
    orphans = _orphans(out_dir, rendered)
    if orphans:
        print("  workflows in the target that this config does not render (left untouched; --prune to remove on apply):")
        for name in orphans:
            print(f"      ? {name}")
    print("\nplan: dry run only — nothing was written.")
    return 0


def _orphans(out_dir: Path, rendered: dict[str, str]) -> list[str]:
    if not out_dir.is_dir():
        return []
    present = {p.name for p in out_dir.glob("*.yml")}
    return sorted(present - set(rendered))


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        rendered = _render_or_fail(args.config, args.platform)
    except render.RenderError as exc:
        print(f"apply: {exc}", file=sys.stderr)
        return 1
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for status, name in _classify(out_dir, rendered):
        if status == "unchanged":
            print(f"  = unchanged {name}")
            continue
        (out_dir / name).write_text(rendered[name])
        written += 1
        print(f"  {'+ wrote    ' if status == 'new' else '~ updated  '} {name}")

    orphans = _orphans(out_dir, rendered)
    for name in orphans:
        if args.prune:
            (out_dir / name).unlink()
            print(f"  - pruned   {name}")
        else:
            print(f"  ? kept     {name} (not rendered by this config; --prune to remove)")
    print(f"\napply: {written} file(s) written, {len(rendered) - written} unchanged"
          + (f", {len(orphans)} orphan(s) pruned" if args.prune else ""))
    return 0


# ------------------------------------------------------------------------------- init


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


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a commented .agentic/config.yml — interactively, or from a profile."""
    if args.profile or args.yes:
        try:
            choices = scaffold.default_choices(args.profile or "standard")
        except ValueError as exc:
            print(f"init: {exc}", file=sys.stderr)
            return 1
    elif sys.stdin.isatty():
        # The wizard is UI: route every prompt and message to stderr so stdout stays reserved for
        # the generated config (`--print`) or the result messages.
        choices = scaffold.run_wizard(read_input=_prompt_from_stdin, write_line=_emit_to_stderr)
    else:
        print(
            "init: not a terminal, and no --profile given.\n"
            "  Run `stagr init` in a terminal for guided setup, or\n"
            "  `stagr init --profile <minimal|standard|full|custom>` to generate a file directly.",
            file=sys.stderr,
        )
        return 1

    text = scaffold.generate(choices)

    # Never let a real credential reach the file or stdout. If a user pastes a token/key VALUE
    # where a secret NAME is expected (an easy onboarding mistake — `ghp_…`, `github_pat_…`, an
    # `sk-…` API key), it can satisfy the secret-name regex and be serialized. Refuse to emit
    # anything in that case; the value belongs only in the CI secret store, referenced by NAME.
    leaked = _SECRET_VALUE_RE.search(text)
    if leaked:
        print("init: an entered value looks like a real credential, not a secret NAME. stagr never\n"
              "  stores secret values — enter the NAME of the secret (its value lives in your CI\n"
              "  secret store). Nothing was written.", file=sys.stderr)
        return 1

    # Validate the generated config BEFORE printing or writing it, so neither `--print` (which a
    # user may redirect into .agentic/config.yml) nor a write ever emits a config that then fails
    # the `doctor`/`plan` step init points at. This catches semantically invalid free-form values
    # the schema alone accepts — a secret name with a hyphen, a branch with whitespace, a model id
    # with expression metacharacters — which the renderer (the single source of truth) rejects.
    try:
        generated_cfg = yaml.safe_load(text)
        render.validate_config(generated_cfg)
        render.render_all(generated_cfg, (generated_cfg.get("platform", {}) or {}).get("type", "github"))
    except (render.RenderError, yaml.YAMLError) as exc:
        print(f"init: the chosen values produce a config the pipeline rejects: {exc}\n"
              "  Nothing was written. Re-run and choose values the message above accepts.",
              file=sys.stderr)
        return 1

    if args.print_only:
        print(text, end="")
        return 0

    dest = args.config
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
    if dest.exists() and not args.force:
        print(f"init: {dest} already exists — use --force to overwrite, or --print to preview.",
              file=sys.stderr)
        return 1
    # Report a write failure (unwritable location, a file where a parent dir is expected, a
    # directory at the destination) as a concise error and exit 1 — not an uncaught traceback.
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    except OSError as exc:
        print(f"init: could not write {dest}: {exc}", file=sys.stderr)
        return 1
    print(f"init: wrote {dest} (profile: {choices['profile']}).")
    # Follow-up commands default to .agentic/config.yml; when init wrote elsewhere, tell the user to
    # pass the same --config so doctor/plan/apply operate on the file they just created.
    # shlex.quote so a path with spaces or shell metacharacters stays one argument when copied.
    config_flag = "" if dest == Path(".agentic/config.yml") else f" --config {shlex.quote(str(dest))}"
    print(f"next: `stagr doctor{config_flag}` to validate, `stagr plan{config_flag}` to preview, "
          f"`stagr apply{config_flag}` to write workflows.")
    return 0


# ------------------------------------------------------------------------------- help


def _subparser_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:  # noqa: SLF001 — argparse exposes subparsers only here
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def cmd_help(args: argparse.Namespace) -> int:
    """`stagr help` lists commands; `stagr help <command>` details one."""
    parser = build_parser()
    topic = getattr(args, "topic", None)
    if not topic:
        parser.print_help()
        return 0
    choices = _subparser_choices(parser)
    if topic in choices:
        choices[topic].print_help()
        return 0
    print(f"help: unknown command '{topic}'. Available: {', '.join(sorted(choices))}", file=sys.stderr)
    return 1


# ----------------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stagr", description="stagr — the agentic-foundation control plane CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_arguments(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--config", default=Path(".agentic/config.yml"), type=Path,
                                    help="path to the .agentic/config.yml contract")
        command_parser.add_argument("--platform", default=None, help="override platform.type (e.g. github)")

    doctor_parser = subparsers.add_parser(
        "doctor", help="validate config + report health, secrets (by NAME), and lanes")
    add_common_arguments(doctor_parser)
    doctor_parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    doctor_parser.set_defaults(func=cmd_doctor)

    plan_parser = subparsers.add_parser("plan", help="dry run: show what apply would write (no writes)")
    add_common_arguments(plan_parser)
    plan_parser.add_argument("--out", default=Path(".github/workflows"), type=Path, help="target workflow dir")
    plan_parser.add_argument("--diff", action="store_true", help="show a unified diff for changed workflows")
    plan_parser.set_defaults(func=cmd_plan)

    apply_parser = subparsers.add_parser("apply", help="render the pipeline and write it (idempotent)")
    add_common_arguments(apply_parser)
    apply_parser.add_argument("--out", default=Path(".github/workflows"), type=Path, help="target workflow dir")
    apply_parser.add_argument("--prune", action="store_true",
                              help="also delete workflow files in the target that this config does not render")
    apply_parser.set_defaults(func=cmd_apply)

    init_parser = subparsers.add_parser(
        "init", help="scaffold a .agentic/config.yml (interactive, or --profile to generate)")
    init_parser.add_argument("--config", default=Path(".agentic/config.yml"), type=Path, help="output path")
    init_parser.add_argument("--profile", choices=list(scaffold.PROFILES),
                             help="generate non-interactively from this profile (skips the wizard)")
    init_parser.add_argument("--print", dest="print_only", action="store_true",
                             help="print to stdout; write nothing")
    init_parser.add_argument("--force", action="store_true", help="overwrite an existing config file")
    init_parser.add_argument("--yes", action="store_true",
                             help="accept defaults without prompting (profile defaults to standard)")
    init_parser.set_defaults(func=cmd_init)

    help_parser = subparsers.add_parser("help", help="show help for all commands, or `stagr help <command>`")
    help_parser.add_argument("topic", nargs="?", help="a command name to describe in detail")
    help_parser.set_defaults(func=cmd_help)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Accept `stagr <command> help` as an alias for `stagr help <command>`.
    if len(argv) == 2 and argv[1] == "help" and argv[0] != "help":
        argv = ["help", argv[0]]
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
