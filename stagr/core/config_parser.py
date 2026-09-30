"""Config file parsing for the neutral core (V-S01 / V-S02).

This module provides ``parse_config``, the front-door entry point for reading
an ``.agentic/config.yml`` file.  It is deliberately minimal: it reads the
file, parses the YAML, and enforces the ``version`` contract (V-S02) before
returning the raw config dict.  All subsequent validation (schema, stage-graph
invariants, semantic checks) is the responsibility of the caller.

The only supported ``version`` value is the integer ``2``.  Any other value —
including a string ``"2"``, an integer ``1``, or a missing ``version`` key —
raises ``ConfigVersionError`` with the offending value.

Design source: design-docs/02-canonical-stage-model.md, issue #197.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigSyntaxError, ConfigVersionError

# V-S02: the single supported config version.
SUPPORTED_VERSION: int = 2


def parse_config(config_path: Path) -> dict[str, Any]:
    """Read and parse an ``.agentic/config.yml`` file, validating the version field.

    Opens ``config_path``, parses it as YAML, enforces that ``version`` is the
    integer ``2`` (V-S02), and returns the raw config dict.  The returned dict
    is the unmodified result of ``yaml.safe_load`` — no defaults are applied,
    and no schema validation is performed here.  Those steps belong to the
    render pipeline.

    Args:
        config_path: Absolute or relative ``Path`` to the config file.  The
            caller is responsible for confirming the path is within the project
            root (path-confinement is a render-layer concern, not a parsing
            concern).

    Returns:
        The raw config ``dict`` exactly as parsed from YAML.

    Raises:
        OSError: If ``config_path`` cannot be opened or read.
        ConfigSyntaxError: If the file content is not valid YAML. The message names the line and
            column only, never the text the YAML parser quoted.
        ConfigVersionError: If ``config["version"]`` is not the integer ``2``.
            Also raised when the top-level document is not a mapping (because
            a missing or non-integer ``version`` key is then equally invalid).
    """
    with config_path.open(encoding="utf-8") as config_file:
        try:
            raw_config = yaml.safe_load(config_file)
        except yaml.YAMLError as yaml_error:
            raise ConfigSyntaxError(_describe_yaml_position(yaml_error)) from None

    if not isinstance(raw_config, dict):
        # A non-mapping document has no version key — treat it as version=None
        # so the error message is consistent with a missing-key case.
        raise ConfigVersionError(None)

    version = raw_config.get("version")
    if type(version) is not int or version != SUPPORTED_VERSION:
        raise ConfigVersionError(version)

    return raw_config


def _describe_yaml_position(yaml_error: yaml.YAMLError) -> str:
    """Return "config is not valid YAML at line N, column M" without any quoted config text."""
    error_mark = getattr(yaml_error, "problem_mark", None) or getattr(yaml_error, "context_mark", None)
    if error_mark is None:
        return "config is not valid YAML"
    return (
        f"config is not valid YAML at line {error_mark.line + 1}, column {error_mark.column + 1}; "
        "fix the syntax there (the parser's message is withheld because it can quote config text)"
    )
