"""Neutral-core and render-pipeline error types.

``ConfigVersionError`` is raised by ``parse_config`` (V-S02) when the version
field in a config file is not the supported integer 2.

``ConfigSyntaxError`` is raised by ``parse_config`` when the file is not valid YAML. It carries the
line and column, never the parser's message, because that message can quote config text and a
config may hold a pasted secret.

``ConfigSchemaError`` is raised by ``validate_config`` when the config does not conform to
``stagr/config.schema.json``.

``SecretAliasResolutionError`` is raised during the Phase 1 rendering loop. It
is distinct from normalization-time errors (``ConfigError``,
``StaticValidationError`` in models.py) because it occurs after the normalized
stage graph has been validated.
"""
from __future__ import annotations


class ConfigVersionError(ValueError):
    """Raised when the config file's ``version`` field is not the supported value.

    V-S02: the only supported version is ``2`` (integer). Any other value —
    including a string ``"2"``, an integer ``1``, or a missing ``version`` key
    — causes this error to be raised by ``parse_config``.

    ``found_version`` carries the actual value read from the file (or ``None``
    when the key is absent), so callers and test assertions can inspect it
    without parsing the error message.
    """

    def __init__(self, found_version: object) -> None:
        self.found_version = found_version
        super().__init__(
            f"unsupported config version {found_version!r}; "
            "the only supported version is 2 (integer)"
        )


class ConfigSyntaxError(ValueError):
    """Raised when the config file is not valid YAML.

    The message gives the line and column of the problem and nothing the parser quoted: a PyYAML
    message can echo config text (for example ``could not determine a constructor for the tag
    '!<text>'``), and text in a secret-name field must never reach CLI or CI logs.
    """


class ConfigSchemaError(ValueError):
    """Raised when the config does not conform to ``stagr/config.schema.json``.

    The message lists every violation as ``<path>: <problem>``; the value of a
    ``*_secret`` field is never included (see ``describe_schema_error``).
    """


class SecretAliasResolutionError(Exception):
    """Raised when a SecretRef alias has no mapping in provider_config.

    The Phase 1 alias resolution step looks up each SecretRef.alias in
    ``provider_config["providers"][<provider>]["secrets"][<alias>]``. When
    an alias is absent from that mapping, this error is raised before the
    PlatformRenderer is called for the affected stage.

    The error message names the stage, the provider, and the unresolvable alias
    so the operator can correct their provider configuration.
    """
