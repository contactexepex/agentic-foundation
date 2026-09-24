"""doctor / health-report tests (secret-by-NAME, model resolution, fail-loud)."""
from __future__ import annotations

import io
from contextlib import redirect_stdout

from .harness import REPO_ROOT, SECRET_VALUE, _project_dir, check, cli, render


def test_report() -> None:
    cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    rep = cli.collect_report(cfg, "github")
    check(rep["profile"] == "custom" and rep["default_branch"] == "main", "doctor: platform basics")
    ids = {s["id"] for s in rep["stages"]}
    # implement-codex is a disabled roadmap stage (Codex implementer not rendered yet), so it is
    # dropped from the expanded graph; the active stages are the Claude implementer + Codex reviewers.
    check({"implement-claude", "review", "security"} <= ids, "doctor: stages present")
    check("implement-codex" not in ids, "doctor: disabled roadmap codex implementer is dropped")
    # anthropic implementer (Claude Code) resolves a real model; codex stages are app-supplied.
    impl = next(s for s in rep["stages"] if s["id"] == "implement-claude")
    check(impl["model"] == "claude-sonnet-5", "doctor: anthropic implementer model resolved")
    # secret NAMES surfaced, never values. The anthropic implementer (Claude Code) needs
    # ANTHROPIC_API_KEY; the openai stages run via the Codex app, so OPENAI_API_KEY is NOT
    # required (the app does not read a provider API key); the codex review lane needs the PAT.
    check("ANTHROPIC_API_KEY" in rep["secret_names"], "doctor: anthropic key secret NAME surfaced")
    check("OPENAI_API_KEY" not in rep["secret_names"],
          "doctor: openai key NOT required when openai is used only via the codex app backend")
    check("REMEDIATION_TOKEN" in rep["secret_names"], "doctor: codex review PAT NAME surfaced")
    check("request-review.yml" in rep["workflows"], "doctor: review lane in render set")
    check(not rep["problems"], "doctor: healthy config has no problems")

    # An anthropic implement stage (Claude Code) requires the provider key and renders cleanly.
    anthro_cfg = {"version": 2, "profile": "custom",
                  "platform": {"type": "github", "default_branch": "main"},
                  "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "m"}}},
                  "stages": [{"id": "impl", "type": "implement", "provider": "anthropic"}]}
    rep_anthro = cli.collect_report(anthro_cfg, "github")
    check("ANTHROPIC_API_KEY" in rep_anthro["secret_names"],
          "doctor: anthropic key IS required for the Claude implementer")
    check(not rep_anthro["problems"], "doctor: anthropic implement config is healthy")

    # A codex review stage WITHOUT pr_updated renders no push-review lane, so doctor must NOT ask for
    # the review PAT — the secret predicate mirrors lane selection.
    no_push_cfg = {"version": 2, "profile": "custom",
                   "platform": {"type": "github", "default_branch": "main"},
                   "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "m"}}},
                   "stages": [{"id": "review", "type": "review", "provider": "openai", "triggers": ["pr_opened"]}]}
    rep_no_push = cli.collect_report(no_push_cfg, "github")
    check("REMEDIATION_TOKEN" not in rep_no_push["secret_names"],
          "doctor: no review PAT required when no push-review lane renders")


def test_doctor_no_secret_values_and_exit() -> None:
    # doctor over the dogfood config prints only NAMES, never a secret value; exits 0.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["doctor", "--config", str(REPO_ROOT / ".agentic" / "config.yml")])
    out = buf.getvalue()
    check(rc == 0, "doctor: healthy config exits 0")
    check(SECRET_VALUE.search(out) is None, "doctor: prints no secret value")
    check("REMEDIATION_TOKEN" in out, "doctor: prints the secret NAME")


def test_doctor_fail_loud() -> None:
    with _project_dir() as d:
        bad = d / "config.yml"
        bad.write_text(
            "version: 2\nprofile: custom\n"
            "platform: {type: github, default_branch: main}\n"
            "defaults: {provider: openai, models: {}}\n"
            "stages:\n  - {id: implement, type: implement, backend: {name: generic}}\n"
        )
        # The config sits inside the project root the CLI confines `--config` to, so this exercises
        # the model-resolution failure (not the containment guard).
        rc = cli.main(["doctor", "--config", "config.yml", "--json"])
        check(rc == 1, "doctor: unresolvable generic implementer model exits 1")
