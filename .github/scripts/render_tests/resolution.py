"""Model-resolution, profile-expansion, and generic-backend assembly tests."""
from __future__ import annotations

import re

from .harness import build_invocation, check, expect_raises, render


def test_resolution() -> None:
    cfg = {
        "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "c-def", "tiers": {"complex": "c-cx"}}, "openai": {"default": "o-def"}}},
        "models": {"aliases": {"strong": {"anthropic": "c-strong", "openai": "o-strong"}}},
    }
    # precedence: per-request > stage > defaults
    check(render.resolve_model(cfg, {"id": "s", "provider": "anthropic"}, "standard") == "c-def", "resolve: defaults.default")
    check(render.resolve_model(cfg, {"id": "s", "provider": "anthropic"}, "complex") == "c-cx", "resolve: defaults tier")
    check(render.resolve_model(cfg, {"id": "s", "provider": "anthropic", "model": {"default": "c-stage"}}, "standard") == "c-stage", "resolve: stage overrides default")
    check(render.resolve_model(cfg, {"id": "s", "provider": "anthropic"}, "standard", request_override="c-req") == "c-req", "resolve: per-request wins")
    # alias expansion per provider
    check(render.resolve_model(cfg, {"id": "s", "provider": "openai", "model": {"default": "strong"}}, "standard") == "o-strong", "resolve: alias expands per provider")
    # fail loud when nothing resolves
    expect_raises(lambda: render.resolve_model({"defaults": {}}, {"id": "s", "provider": "anthropic"}, "standard"), "resolve: fail loud when unresolved")
    # fail loud when provider missing
    expect_raises(lambda: render.resolve_model({"defaults": {}}, {"id": "s"}, "standard"), "resolve: fail loud when no provider")


def test_profile_expansion() -> None:
    ids = [s["id"] for s in render.expand_stages({"profile": "standard"})]
    check(ids == ["implement", "review", "security"], "profile: standard expands to implement/review/security")
    # #77: the dev-lane `full` profile drops plan/docs (they belong to the Planning/CD sibling toolkits).
    full_ids = [s["id"] for s in render.expand_stages({"profile": "full"})]
    check(full_ids == ["implement", "security", "test", "integration-test", "review"],
          "profile: full expands to the dev-lane graph without plan/docs")
    # override merges onto profile
    merged = render.expand_stages({"profile": "standard", "stages": [{"id": "review", "provider": "openai"}]})
    review = next(s for s in merged if s["id"] == "review")
    check(review.get("provider") == "openai" and review.get("gate") == "blocking", "profile: listed stage merges onto profile stage")
    # custom = only listed
    check([s["id"] for s in render.expand_stages({"profile": "custom", "stages": [{"id": "x", "type": "custom"}]})] == ["x"], "profile: custom = only listed")
    expect_raises(lambda: render.expand_stages({"profile": "bogus"}), "profile: unknown profile fails loud")


def test_backend() -> None:
    cfg = {"defaults": {"provider": "anthropic"}, "providers": {"openai": {"api_key_secret": "AZ_OPENAI_KEY"}}}
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
    inv2 = build_invocation(cfg, {"id": "implement", "type": "implement", "provider": "anthropic"}, "c-model")
    check(inv2.api_key_secret == "ANTHROPIC_API_KEY" and inv2.action == "implement", "backend: default secret name + implement action")
