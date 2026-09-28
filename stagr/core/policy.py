"""Policy derivation for the neutral-core normalization pipeline.

Implements Group C derivation functions (issues #184–#187). Each function
accepts the raw config dict and returns a frozen, validated policy dataclass.

Issue #184: derive_trust_policy — who and what Stagr-generated automation
may act on behalf of.
"""
from __future__ import annotations

from typing import Any

from .enums import AuthorRole, ForkPolicy
from .models import StaticValidationError, TrustPolicy

_DEFAULT_HUMAN_MERGE_LABEL = "human-merge"
_DEFAULT_TRUSTED_ROLES: tuple[AuthorRole, ...] = (
    AuthorRole.OWNER,
    AuthorRole.MEMBER,
    AuthorRole.COLLABORATOR,
)


def derive_trust_policy(config: dict[str, Any]) -> TrustPolicy:
    """Derive a TrustPolicy from the raw M1 config dict.

    Reads ``platform.trusted_roles``, ``platform.same_repo_only``, and
    ``platform.labels.human_merge``.

    Derivation rules
    ----------------
    - ``platform.trusted_roles`` → tuple of :class:`AuthorRole` values.
      When the key is absent the schema default applies: OWNER, MEMBER, and
      COLLABORATOR.  An explicit empty list produces an empty tuple.
      Each string must match a recognised :class:`AuthorRole` member; an
      unrecognised string raises :class:`~stagr.core.models.StaticValidationError`
      with code ``V-S14``.  ``CONTRIBUTOR`` is never added implicitly — only
      roles the operator explicitly lists appear in ``trusted_roles``.
    - ``platform.same_repo_only`` → :class:`ForkPolicy` member.  ``true``
      (the default when the key is absent) maps to :attr:`ForkPolicy.DENY`;
      ``false`` maps to :attr:`ForkPolicy.ALLOW_UNPRIVILEGED`.
    - ``platform.labels.human_merge`` → ``human_merge_label`` string.
      Defaults to ``"human-merge"`` when absent.

    Parameters
    ----------
    config:
        The raw YAML config dict (top-level, as loaded by ``yaml.safe_load``).

    Returns
    -------
    TrustPolicy
        An immutable, validated trust-policy dataclass.

    Raises
    ------
    StaticValidationError
        When any element of ``platform.trusted_roles`` is not a recognised
        :class:`AuthorRole` value (check code ``V-S14``).
    """
    platform_config: dict[str, Any] = config.get("platform", {}) or {}

    trusted_roles = _derive_trusted_roles(platform_config)
    fork_policy = _derive_fork_policy(platform_config)
    human_merge_label = _derive_human_merge_label(platform_config)

    return TrustPolicy(
        trusted_roles=trusted_roles,
        fork_policy=fork_policy,
        human_merge_label=human_merge_label,
    )


def _derive_trusted_roles(platform_config: dict[str, Any]) -> tuple[AuthorRole, ...]:
    if "trusted_roles" not in platform_config:
        return _DEFAULT_TRUSTED_ROLES
    raw_role_strings: list[str] = platform_config["trusted_roles"] or []
    valid_role_values = {member.value for member in AuthorRole}

    validated_roles: list[AuthorRole] = []
    for raw_role in raw_role_strings:
        role_string = str(raw_role).lower()
        if role_string not in valid_role_values:
            raise StaticValidationError(
                f"V-S14: unrecognised trusted_role '{raw_role}'. "
                f"Valid values: {sorted(valid_role_values)}"
            )
        validated_roles.append(AuthorRole(role_string))

    return tuple(validated_roles)


def _derive_fork_policy(platform_config: dict[str, Any]) -> ForkPolicy:
    same_repo_only: bool = platform_config.get("same_repo_only", True)
    if same_repo_only:
        return ForkPolicy.DENY
    return ForkPolicy.ALLOW_UNPRIVILEGED


def _derive_human_merge_label(platform_config: dict[str, Any]) -> str:
    labels_config: dict[str, Any] = platform_config.get("labels", {}) or {}
    return str(labels_config.get("human_merge", _DEFAULT_HUMAN_MERGE_LABEL))
