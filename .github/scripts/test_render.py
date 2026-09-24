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


def main() -> int:
    test_resolution()
    test_profile_expansion()
    test_backend()
    test_new_behaviors()
    test_render_structural()
    if failures:
        print(f"\n{len(failures)} test failure(s).", file=sys.stderr)
        return 1
    print("\nAll M2 renderer/backend tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
