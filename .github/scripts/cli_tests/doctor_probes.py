"""Doctor probe tests: missing-secret and missing-ruleset reporting.

Verifies that `collect_report` / `cmd_doctor` accurately surfaces:

* The required secret NAME when a stage needs a provider API key and the
  operator has not yet configured the secret in CI (missing-secret probe).
* The branch-protection ruleset requirement when `modules.auto_merge` is not
  enabled, so the operator knows to install the ruleset before the pipeline
  is truly gated (missing-ruleset probe).
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout

from .harness import REPO_ROOT, check, cli


# ---------------------------------------------------------------------------
# Minimal helper configs
# ---------------------------------------------------------------------------

def _anthro_cfg(*, custom_secret: str | None = None) -> dict:
    """A minimal anthropic implement config, optionally with a custom api_key_secret."""
    providers: dict = {}
    if custom_secret:
        providers = {"anthropic": {"api_key_secret": custom_secret}}
    cfg: dict = {
        "version": 2,
        "profile": "custom",
        "platform": {"type": "github", "default_branch": "main"},
        "defaults": {
            "provider": "anthropic",
            "models": {"anthropic": {"default": "claude-3-5-sonnet-20241022"}},
        },
        "stages": [{"id": "impl", "type": "implement", "provider": "anthropic"}],
        "modules": {"auto_merge": True},
    }
    if providers:
        cfg["providers"] = providers
    return cfg


def _human_merge_cfg() -> dict:
    """A config where modules.auto_merge is absent (human-merge lane only)."""
    return {
        "version": 2,
        "profile": "custom",
        "platform": {"type": "github", "default_branch": "main"},
        "defaults": {
            "provider": "openai",
            "models": {},
        },
        "stages": [
            {"id": "review", "type": "review", "provider": "openai"},
            {"id": "security", "type": "security", "provider": "openai"},
        ],
        # No modules.auto_merge — human-merge lane, so an external ruleset is required.
    }


# ---------------------------------------------------------------------------
# test_doctor_missing_secret
# ---------------------------------------------------------------------------

def test_doctor_missing_secret() -> None:
    """Doctor accurately surfaces the required secret NAME for a stage that needs a provider key.

    When an operator hasn't configured the secret in CI yet (the secret is "missing"
    from their environment), doctor lists exactly which secret name to add so they can
    act on it. The test covers both the default name and a custom override.
    """
    # Default: no explicit api_key_secret configured → doctor falls back to ANTHROPIC_API_KEY.
    rep = cli.collect_report(_anthro_cfg(), "github")
    check(
        "ANTHROPIC_API_KEY" in rep["secret_names"],
        "doctor missing secret: ANTHROPIC_API_KEY surfaced when api_key_secret is not explicitly set",
    )
    check(not rep["problems"], "doctor missing secret: default-key config is otherwise healthy")

    # Custom override: providers.anthropic.api_key_secret = MY_ANTHRO_KEY.
    # Doctor must report the CUSTOM name, not the default, so the operator configures the right secret.
    rep_custom = cli.collect_report(_anthro_cfg(custom_secret="MY_ANTHRO_KEY"), "github")
    check(
        "MY_ANTHRO_KEY" in rep_custom["secret_names"],
        "doctor missing secret: custom api_key_secret name surfaced accurately",
    )
    check(
        "ANTHROPIC_API_KEY" not in rep_custom["secret_names"],
        "doctor missing secret: default name NOT emitted when a custom name is configured",
    )
    check(not rep_custom["problems"], "doctor missing secret: custom-key config is otherwise healthy")

    # CLI smoke check: doctor text output names the secret and exits 0 for a healthy config.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(
            ["doctor", "--config", str(REPO_ROOT / ".agentic" / "config.yml")]
        )
    out = buf.getvalue()
    check(rc == 0, "doctor missing secret: healthy config exits 0")
    check("ANTHROPIC_API_KEY" in out, "doctor missing secret: secret NAME appears in text output")


# ---------------------------------------------------------------------------
# test_doctor_missing_ruleset
# ---------------------------------------------------------------------------

def test_doctor_missing_ruleset() -> None:
    """Doctor accurately surfaces the branch-protection ruleset requirement.

    When modules.auto_merge is not enabled, stagr renders no merge-gate workflow.
    Merge-gate enforcement then relies entirely on a GitHub branch-protection ruleset
    configured by the operator. Doctor notes this requirement so the operator knows
    the ruleset is missing from their repository setup.
    """
    # Human-merge config (no modules.auto_merge) → ruleset note must be present.
    rep = cli.collect_report(_human_merge_cfg(), "github")
    notes = rep.get("notes", [])
    check(
        any("ruleset" in note.lower() for note in notes),
        "doctor missing ruleset: ruleset note present when modules.auto_merge is not enabled",
    )
    check(
        not rep["problems"],
        "doctor missing ruleset: human-merge config has no config-level problems (valid config)",
    )

    # auto_merge explicitly false → same as absent; ruleset note must appear.
    rep_false = cli.collect_report(
        {**_human_merge_cfg(), "modules": {"auto_merge": False}}, "github"
    )
    check(
        any("ruleset" in note.lower() for note in rep_false.get("notes", [])),
        "doctor missing ruleset: ruleset note present when modules.auto_merge is explicitly false",
    )

    # auto_merge enabled → stagr renders the merge gate, but the org ruleset is still
    # required to prevent direct pushes; the note must appear regardless of auto_merge.
    auto_merge_cfg = {
        **_human_merge_cfg(),
        "modules": {"auto_merge": True},
        "routing": {"fast_path": {"enabled": False}},
    }
    rep_am = cli.collect_report(auto_merge_cfg, "github")
    check(
        any("ruleset" in note.lower() for note in rep_am.get("notes", [])),
        "doctor missing ruleset: ruleset note always present (org ruleset guards against direct pushes regardless of auto_merge)",
    )
