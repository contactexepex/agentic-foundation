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

This package was split from a single `cli.py` module into cohesive submodules; this `__init__`
re-exports every top-level name so `from stagr import cli; cli.<name>` keeps working unchanged.
"""
from __future__ import annotations

from .report import (
    DEFAULT_CONFIG_PATH,
    _key_secret_name,
    _load_validated,
    _stage_provider,
    collect_report,
)
from .doctor import cmd_doctor
from .plan_apply import (
    _classify,
    _orphans,
    _render_or_fail,
    cmd_apply,
    cmd_plan,
)
from .init import (
    _REPARSE_POINT_ATTR,
    _SECRET_VALUE_RE,
    _emit_to_stderr,
    _generated_config_is_valid,
    _is_reparse_point,
    _print_init_next_steps,
    _prompt_from_stdin,
    _resolve_init_choices,
    _symlink_in_chain,
    _write_generated_config,
    cmd_init,
)
from .parser import (
    _subparser_choices,
    build_parser,
    cmd_help,
    main,
)
