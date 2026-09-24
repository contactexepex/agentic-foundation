#!/usr/bin/env python3
"""Tests for the M2 renderer + generic backend.

Runnable with plain `python .github/scripts/test_render.py` (no pytest needed).
Covers: model-resolution precedence/alias/fail-loud, profile expansion, generic
backend assembly (secret-by-name, no secret values, action mapping), and STRUCTURAL
validity + determinism of the rendered GitHub workflows. Exit 0 = pass.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "install"))

import render  # noqa: E402
from backends.generic import build_invocation  # noqa: E402

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"OK  {msg}")
    else:
        failures.append(msg)
        print(f"FAIL {msg}", file=sys.stderr)


def expect_raises(fn, msg: str) -> None:
    try:
        fn()
        failures.append(msg)
        print(f"FAIL {msg} (no error raised)", file=sys.stderr)
    except render.RenderError:
        print(f"OK  {msg}")


def test_resolution() -> None:
    cfg = {
        "defaults": {"provider": "claude", "models": {"claude": {"default": "c-def", "tiers": {"complex": "c-cx"}}, "openai": {"default": "o-def"}}},
        "models": {"aliases": {"strong": {"claude": "c-strong", "openai": "o-strong"}}},
    }
    # precedence: per-request > stage > defaults
    check(render.resolve_model(cfg, {"id": "s", "provider": "claude"}, "standard") == "c-def", "resolve: defaults.default")
    check(render.resolve_model(cfg, {"id": "s", "provider": "claude"}, "complex") == "c-cx", "resolve: defaults tier")
    check(render.resolve_model(cfg, {"id": "s", "provider": "claude", "model": {"default": "c-stage"}}, "standard") == "c-stage", "resolve: stage overrides default")
    check(render.resolve_model(cfg, {"id": "s", "provider": "claude"}, "standard", request_override="c-req") == "c-req", "resolve: per-request wins")
    # alias expansion per provider
    check(render.resolve_model(cfg, {"id": "s", "provider": "openai", "model": {"default": "strong"}}, "standard") == "o-strong", "resolve: alias expands per provider")
    # fail loud when nothing resolves
    expect_raises(lambda: render.resolve_model({"defaults": {}}, {"id": "s", "provider": "claude"}, "standard"), "resolve: fail loud when unresolved")
    # fail loud when provider missing
    expect_raises(lambda: render.resolve_model({"defaults": {}}, {"id": "s"}, "standard"), "resolve: fail loud when no provider")


def test_profile_expansion() -> None:
    ids = [s["id"] for s in render.expand_stages({"profile": "standard"})]
    check(ids == ["implement", "review", "security"], "profile: standard expands to implement/review/security")
    # override merges onto profile
    merged = render.expand_stages({"profile": "standard", "stages": [{"id": "review", "provider": "openai"}]})
    review = next(s for s in merged if s["id"] == "review")
    check(review.get("provider") == "openai" and review.get("gate") == "blocking", "profile: listed stage merges onto profile stage")
    # custom = only listed
    check([s["id"] for s in render.expand_stages({"profile": "custom", "stages": [{"id": "x", "type": "custom"}]})] == ["x"], "profile: custom = only listed")
    expect_raises(lambda: render.expand_stages({"profile": "bogus"}), "profile: unknown profile fails loud")


def test_backend() -> None:
    cfg = {"defaults": {"provider": "claude"}, "providers": {"openai": {"api_key_secret": "AZ_OPENAI_KEY"}}}
    inv = build_invocation(cfg, {"id": "review", "type": "review", "provider": "openai", "skill": "code-review", "gate": "blocking"}, "o-model")
    check(inv.action == "review", "backend: review type -> review action")
    check(inv.api_key_secret == "AZ_OPENAI_KEY", "backend: uses configured secret NAME")
    check(inv.model == "o-model", "backend: carries resolved model")
    check("Code Review" in inv.system_prompt, "backend: skill methodology embedded")
    check("untrusted DATA" in inv.system_prompt, "backend: guardrail frame present")
    # no secret VALUE anywhere in the invocation
    blob = str(inv.to_dict())
    check(not re.search(r"sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}", blob), "backend: no secret value in invocation")
    # default secret name when provider not configured
    inv2 = build_invocation(cfg, {"id": "implement", "type": "implement", "provider": "claude"}, "c-model")
    check(inv2.api_key_secret == "ANTHROPIC_API_KEY" and inv2.action == "implement", "backend: default secret name + implement action")


def test_render_structural() -> None:
    cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    render.validate_config(cfg)
    rendered = render.render_all(cfg, "github")
    check(len(rendered) >= 1, "render: produced at least one workflow")
    for name, content in rendered.items():
        # no unresolved renderer tokens ({{ token }}) — GitHub's own ${{ ... }} expressions
        # are intentionally NOT matched by render._TOKEN, so they are left intact.
        check(render._TOKEN.search(content) is None, f"render: {name} has no unresolved tokens")
        # valid YAML with required top-level keys
        doc = yaml.safe_load(content)
        check(isinstance(doc, dict) and "jobs" in doc and "permissions" in doc, f"render: {name} has jobs + permissions")
        check(True if "on" in doc or True in doc else False, f"render: {name} has triggers")
        # no secret values inlined
        check(not re.search(r"sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}", content), f"render: {name} inlines no secret value")
    # deterministic
    check(render.render_all(cfg, "github") == rendered, "render: deterministic / idempotent")


def test_new_behaviors() -> None:
    import tempfile

    # extends: base merged before child; child wins
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "base.yml").write_text("version: 2\ndefaults:\n  provider: claude\n  models:\n    claude: {default: c-base}\n")
        (dp / "child.yml").write_text("version: 2\nextends: base.yml\nprofile: custom\ndefaults:\n  models:\n    openai: {default: o-child}\n")
        merged = render.load_config(dp / "child.yml")
        check(merged["defaults"]["provider"] == "claude", "extends: inherits base provider")
        check(merged["defaults"]["models"]["claude"]["default"] == "c-base", "extends: inherits base model")
        check(merged["defaults"]["models"]["openai"]["default"] == "o-child", "extends: child adds model")

    # from-preset expansion: a stage with only id+from gains the preset's type/skill
    stages = render.expand_stages({"profile": "custom", "stages": [{"id": "review", "from": "code-review"}]})
    rv = next(s for s in stages if s["id"] == "review")
    check(rv.get("type") == "review" and rv.get("skill") == "code-review", "from: preset supplies type + skill")

    # build_steps includes the configured command
    steps = render._build_steps({"build": {"commands": {"test": "make test"}}})
    check("make test" in steps, "build_steps: includes configured test command")
    check("No build commands" in render._build_steps({}), "build_steps: empty -> no-op message")

    # fail-loud: a generic-backed stage with no resolvable model raises during render
    expect_raises(
        lambda: render.build_context({"profile": "custom", "defaults": {"provider": "openai", "models": {}},
                                      "stages": [{"id": "implement", "type": "implement", "backend": {"name": "generic"}}]}),
        "render: build_context fails loud on unresolved generic implementer model",
    )
    # app-backed implement stage with no model does NOT raise (backend supplies it)
    try:
        render.build_context({"profile": "custom", "defaults": {"provider": "openai", "models": {}},
                              "stages": [{"id": "implement", "type": "implement", "backend": {"name": "codex"}}]})
        print("OK  render: app-backed implementer needs no resolved model")
    except render.RenderError:
        failures.append("app-backed implementer must not require a model")
        print("FAIL app-backed implementer must not require a model", file=sys.stderr)


def test_round2_fixes() -> None:
    import tempfile

    # duplicate explicit stage id -> fail loud
    expect_raises(
        lambda: render.expand_stages({"profile": "custom", "stages": [{"id": "a", "type": "review"}, {"id": "a", "type": "security"}]}),
        "expand_stages: duplicate explicit id fails loud",
    )

    # diamond extends (two bases share an ancestor) must NOT raise circular
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "org.yml").write_text("version: 2\ndefaults: {provider: claude}\n")
        (dp / "teamA.yml").write_text("version: 2\nextends: org.yml\n")
        (dp / "teamB.yml").write_text("version: 2\nextends: org.yml\n")
        (dp / "repo.yml").write_text("version: 2\nprofile: custom\nextends: [teamA.yml, teamB.yml]\n")
        merged = render.load_config(dp / "repo.yml")
        check(merged["defaults"]["provider"] == "claude", "extends: diamond (shared ancestor) resolves, no false cycle")

    # preset pre-fills commands; multiline command indents every line -> valid YAML
    steps = render._build_steps({"build": {"preset": "python"}})
    check("pytest" in steps, "build_steps: preset python pre-fills commands")
    ml = render._build_steps({"build": {"commands": {"test": "echo one\necho two"}}})
    check("\n          echo two" in ml, "build_steps: multiline command lines are all indented")

    # default_branch with YAML flow syntax renders as valid YAML (quoted)
    import yaml as _yaml
    rendered = render.render_all(
        {"version": 2, "profile": "custom", "platform": {"type": "github", "default_branch": "release,2026"},
         "defaults": {"provider": "claude", "models": {"claude": {"default": "c"}}},
         "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}]},
        "github",
    )
    doc = _yaml.safe_load(rendered["validate.yml"])
    on_block = doc.get("on", doc.get(True))  # YAML parses the `on:` key as boolean True
    check(on_block["push"]["branches"] == ["release,2026"], "render: odd default_branch stays one quoted branch filter")

    # instructions as a file path is loaded
    inv = build_invocation({"defaults": {"provider": "claude"}},
                           {"id": "x", "type": "custom", "provider": "claude", "instructions": "templates/skills/code-review/SKILL.md"}, "m")
    check("Code Review" in inv.system_prompt, "backend: instructions file path is loaded as content")


def test_round3_fixes() -> None:
    from backends.generic import runner as gen

    # redact_secrets: default true; guardrails toggle propagates to the invocation.
    inv = build_invocation({"defaults": {"provider": "claude"}},
                           {"id": "r", "type": "review", "provider": "claude"}, "m")
    check(inv.redact_secrets is True, "backend: redact_secrets defaults true")
    inv_off = build_invocation({"defaults": {"provider": "claude"}, "guardrails": {"redact_secrets_in_context": False}},
                               {"id": "r", "type": "review", "provider": "claude"}, "m")
    check(inv_off.redact_secrets is False and "redact_secrets" in inv_off.to_dict(),
          "backend: redact_secrets_in_context=false propagates to Invocation")

    # provider connection settings (base_url/api_version/deployment + extra_headers_secret NAME) carried.
    cfg = {"defaults": {"provider": "azure_openai"},
           "providers": {"azure_openai": {"api_key_secret": "AZ_KEY", "base_url": "https://x.openai.azure.com",
                                          "api_version": "2024-02-01", "deployment": "gpt4o",
                                          "extra_headers_secret": "AZ_EXTRA_HEADERS"}}}
    inv2 = build_invocation(cfg, {"id": "i", "type": "implement", "provider": "azure_openai"}, "gpt4o")
    check(inv2.base_url == "https://x.openai.azure.com" and inv2.api_version == "2024-02-01"
          and inv2.deployment == "gpt4o" and inv2.extra_headers_secret == "AZ_EXTRA_HEADERS",
          "backend: provider connection settings carried in invocation")
    check(inv2.api_key_secret == "AZ_KEY", "backend: provider api_key_secret still a NAME")

    # path confinement: a skills-registry path escaping the repo is rejected.
    try:
        gen.load_skill("evil", {"skills": {"evil": {"source": "path", "path": "../../../../../../etc/passwd"}}})
        failures.append("load_skill must reject a path outside the repo")
        print("FAIL load_skill must reject a path outside the repo", file=sys.stderr)
    except ValueError:
        print("OK  backend: load_skill rejects an out-of-repo skill path")

    # path confinement: an absolute instructions path is rejected (never embedded in the prompt).
    try:
        build_invocation({"defaults": {"provider": "claude"}},
                         {"id": "x", "type": "custom", "provider": "claude", "instructions": "/etc/passwd"}, "m")
        failures.append("build_invocation must reject an absolute out-of-repo instructions path")
        print("FAIL build_invocation must reject an absolute instructions path", file=sys.stderr)
    except ValueError:
        print("OK  backend: instructions path outside the repo is rejected")

    # inline instructions containing a slash but not a real file stay inline (not treated as a path).
    inv3 = build_invocation({"defaults": {"provider": "claude"}},
                            {"id": "x", "type": "custom", "provider": "claude",
                             "instructions": "Compare branch a/b and summarize"}, "m")
    check("Compare branch a/b" in inv3.system_prompt, "backend: non-file instructions stay inline")

    # URI extends fails loud.
    expect_raises(lambda: render.resolve_extends({"extends": "https://example.com/base.yml"}, REPO_ROOT),
                  "extends: URI base fails loud")
    # URI skill source fails loud at validation.
    expect_raises(lambda: render._validate_semantics({"skills": {"s": {"source": "uri", "uri": "https://x/y"}}}),
                  "validate: source: uri skill fails loud")


def test_pipeline_selection() -> None:
    # A codex-backed review/security stage -> the review lane is emitted.
    cfg = render.load_config(REPO_ROOT / ".agentic" / "config.yml")
    rendered = render.render_all(cfg, "github")
    for name in ("validate.yml", "review-router.yml", "implementor.yml",
                 "request-review.yml", "resolve-threads.yml"):
        check(name in rendered, f"select: {name} emitted for codex-review config")
    # The codex PAT is referenced by NAME (from platform.auth.token_secret), never a value.
    check("secrets.CODEX_REMEDIATION_TOKEN" in rendered["request-review.yml"],
          "select: codex_review_secret NAME substituted into request-review")
    check(not re.search(r"ghp_[A-Za-z0-9]{8,}", rendered["resolve-threads.yml"]),
          "select: resolve-threads inlines no secret value")

    # No codex review stage -> the review lane is NOT emitted (module-aware, not glob-all).
    minimal = {"version": 2, "profile": "custom",
               "platform": {"type": "github", "default_branch": "main"},
               "defaults": {"provider": "claude", "models": {"claude": {"default": "c"}}},
               "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}]}
    r2 = render.render_all(minimal, "github")
    check("request-review.yml" not in r2 and "resolve-threads.yml" not in r2,
          "select: no review lane without a codex review stage")
    check("validate.yml" in r2, "select: core pipeline still emitted")


def main() -> int:
    test_resolution()
    test_profile_expansion()
    test_backend()
    test_new_behaviors()
    test_round2_fixes()
    test_round3_fixes()
    test_pipeline_selection()
    test_render_structural()
    if failures:
        print(f"\n{len(failures)} test failure(s).", file=sys.stderr)
        return 1
    print("\nAll M2 renderer/backend tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
