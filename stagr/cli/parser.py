"""Argument parser wiring, the `help` command, and the `main` entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import scaffold
from .report import DEFAULT_CONFIG_PATH
from .doctor import cmd_doctor
from .plan_apply import cmd_apply, cmd_plan
from .init import cmd_init


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stagr", description="stagr — the agentic-foundation control plane CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_arguments(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, type=Path,
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
    init_parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, type=Path, help="output path")
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
