"""Config-layering regression tests: org-default -> per-repo override.

Issue #119 — three scenarios that must hold:
  1. A repo override changes only the overridden field; base values are preserved.
  2. Removing an override falls back to the base value.
  3. An empty repo config (only ``extends``) inherits the base unchanged.

These exercise ``load_config`` / ``resolve_extends`` end-to-end: YAML files are written
to a temp directory that becomes the project root (CWD), mirroring how ``stagr`` is run
from a real repository checkout.
"""
from __future__ import annotations

import yaml
from pathlib import Path

from .harness import _project_dir, check, render

# ---------------------------------------------------------------------------
# Shared fixture: a minimal org-default base config with several distinct fields
# that can be selectively overridden and independently verified.
# ---------------------------------------------------------------------------
_ORG_DEFAULT: dict = {
    "version": 2,
    "profile": "custom",
    "platform": {"type": "github", "default_branch": "main"},
    "defaults": {
        "provider": "anthropic",
        "models": {"anthropic": {"default": "base-model"}},
    },
    "build": {
        "preset": "custom",
        "commands": {
            "test": "make test",
            "lint": "make lint",
        },
    },
    "routing": {"fast_path": {"enabled": False}},
}


def _write(d: Path, name: str, data: dict) -> Path:
    p = d / name
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def test_config_layering() -> None:
    """Regression coverage for org-default -> per-repo override config layering (#119)."""

    with _project_dir() as d:
        _write(d, "org-default.yml", _ORG_DEFAULT)

        # -------------------------------------------------------------------
        # Case 1: empty repo config (only `extends`) inherits the base unchanged
        # -------------------------------------------------------------------
        empty_repo = {"extends": "org-default.yml"}
        resolved = render.load_config(_write(d, "empty-repo.yml", empty_repo))

        check(
            resolved.get("build", {}).get("commands", {}).get("test") == "make test",
            "layering/empty: empty repo inherits base build.commands.test",
        )
        check(
            resolved.get("build", {}).get("commands", {}).get("lint") == "make lint",
            "layering/empty: empty repo inherits base build.commands.lint",
        )
        check(
            resolved.get("defaults", {}).get("models", {}).get("anthropic", {}).get("default") == "base-model",
            "layering/empty: empty repo inherits base defaults.models.anthropic.default",
        )
        check(
            resolved.get("routing", {}).get("fast_path", {}).get("enabled") is False,
            "layering/empty: empty repo inherits base routing.fast_path.enabled",
        )

        # -------------------------------------------------------------------
        # Case 2: repo override changes only the overridden field; all other
        # base values are preserved (deep-merge: overlay wins per-key, not
        # whole-dict replacement).
        # -------------------------------------------------------------------
        repo_override = {
            "extends": "org-default.yml",
            "build": {
                "preset": "custom",
                "commands": {
                    # Override only the test command; leave lint untouched.
                    "test": "pytest --cov",
                },
            },
        }
        resolved_override = render.load_config(_write(d, "repo-override.yml", repo_override))

        check(
            resolved_override.get("build", {}).get("commands", {}).get("test") == "pytest --cov",
            "layering/override: repo override sets build.commands.test",
        )
        check(
            resolved_override.get("build", {}).get("commands", {}).get("lint") == "make lint",
            "layering/override: repo override preserves base build.commands.lint unchanged",
        )
        check(
            resolved_override.get("defaults", {}).get("models", {}).get("anthropic", {}).get("default") == "base-model",
            "layering/override: repo override preserves base defaults.models.anthropic.default",
        )
        check(
            resolved_override.get("routing", {}).get("fast_path", {}).get("enabled") is False,
            "layering/override: repo override preserves base routing.fast_path.enabled",
        )

        # -------------------------------------------------------------------
        # Case 3: removing an override falls back to the base value.
        # A repo config that previously carried an explicit test-command override
        # and had it removed no longer contributes that key; the base value is used.
        # -------------------------------------------------------------------
        no_override = {"extends": "org-default.yml"}
        resolved_removed = render.load_config(_write(d, "no-override.yml", no_override))

        check(
            resolved_removed.get("build", {}).get("commands", {}).get("test") == "make test",
            "layering/fallback: removing test-command override falls back to base value",
        )
        check(
            resolved_removed.get("build", {}).get("commands", {}).get("lint") == "make lint",
            "layering/fallback: removing override does not affect other base values",
        )
