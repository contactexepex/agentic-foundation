"""stagr — the agentic-foundation control plane CLI.

The command line is being rebuilt on the neutral core (`stagr/core/`) and the platform
renderers (`stagr/platforms/`). Until `stagr plan` and `stagr apply` land, the only command is:

    stagr help     # list commands, or `stagr help <command>` / `stagr <command> help`

Design invariants for every command:
  * No network. No secret VALUE is ever read, printed, or logged — only secret NAMES.
  * Fail loud: a config that does not validate exits non-zero with a precise message.
"""
from __future__ import annotations

from .parser import build_parser, cmd_help, main

__all__ = ["build_parser", "cmd_help", "main"]
