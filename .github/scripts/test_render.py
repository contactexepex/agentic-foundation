#!/usr/bin/env python3
"""Tests for the M2 renderer + generic backend.

Runnable with plain `python .github/scripts/test_render.py` (no pytest needed).
Covers: model-resolution precedence/alias/fail-loud, profile expansion, generic
backend assembly (secret-by-name, no secret values, action mapping), and STRUCTURAL
validity + determinism of the rendered GitHub workflows. Exit 0 = pass.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from stagr import render  # noqa: E402
from stagr.backends.generic import build_invocation  # noqa: E402

failures: list[str] = []


@contextmanager
def _project_dir():
    """A temp dir that is also the CWD for the block.

    load_config confines a config's `extends` bases to the project root (the CWD), so a test that
    reads config files from a temp tree must run from inside it (as a real operator runs stagr).
    """
    prev = Path.cwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            yield Path(d)
        finally:
            os.chdir(prev)


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
    # extends: base merged before child; child wins
    with _project_dir() as dp:
        (dp / "base.yml").write_text("version: 2\ndefaults:\n  provider: anthropic\n  models:\n    anthropic: {default: c-base}\n")
        (dp / "child.yml").write_text("version: 2\nextends: base.yml\nprofile: custom\ndefaults:\n  models:\n    openai: {default: o-child}\n")
        merged = render.load_config(dp / "child.yml")
        check(merged["defaults"]["provider"] == "anthropic", "extends: inherits base provider")
        check(merged["defaults"]["models"]["anthropic"]["default"] == "c-base", "extends: inherits base model")
        check(merged["defaults"]["models"]["openai"]["default"] == "o-child", "extends: child adds model")

    # extends confinement: a base resolving OUTSIDE the project root is rejected (untrusted config
    # content must not read an arbitrary host file into the merged contract). Keep BOTH the project
    # and the out-of-repo base inside one managed temp dir so every fixture is cleaned up (never
    # write a predictable sibling like /tmp/outside-base.yml).
    with tempfile.TemporaryDirectory() as outer:
        project = Path(outer) / "project"
        project.mkdir()
        (Path(outer) / "outside-base.yml").write_text("version: 2\ndefaults: {provider: anthropic}\n")
        (project / "child.yml").write_text("version: 2\nextends: ../outside-base.yml\nprofile: custom\n")
        prev = Path.cwd()
        os.chdir(project)
        try:
            expect_raises(
                lambda: render.load_config(project / "child.yml"),
                "extends: a base outside the project root is rejected",
            )
        finally:
            os.chdir(prev)

    # from-preset expansion: a stage with only id+from gains the preset's type/skill
    stages = render.expand_stages({"profile": "custom", "stages": [{"id": "review", "from": "code-review"}]})
    rv = next(s for s in stages if s["id"] == "review")
    check(rv.get("type") == "review" and rv.get("skill") == "code-review", "from: preset supplies type + skill")

    # build_steps includes the configured command
    steps = render._build_steps({"build": {"commands": {"test": "make test"}}})
    check("make test" in steps, "build_steps: includes configured test command")
    check("No build commands" in render._build_steps({}), "build_steps: empty -> no-op message")

    # the implementer runs Claude Code, so a non-claude-code-action implement tool fails loud rather
    # than rendering the Claude workflow with the wrong provider's model/key.
    expect_raises(
        lambda: render.build_context({"profile": "custom", "defaults": {"provider": "openai", "models": {}},
                                      "stages": [{"id": "implement", "type": "implement", "backend": {"name": "generic"}}]}),
        "render: non-Anthropic implement tool (generic) fails loud",
    )
    expect_raises(
        lambda: render.build_context({"profile": "custom", "defaults": {"provider": "openai", "models": {}},
                                      "stages": [{"id": "implement", "type": "implement", "backend": {"name": "codex"}}]}),
        "render: codex implement stage fails loud (not a rendered implementer)",
    )
    # provider openai + an explicit claude-code-action backend must still fail: the implementer reads
    # ANTHROPIC_API_KEY, so the effective PROVIDER (not just the tool) must be anthropic.
    expect_raises(
        lambda: render.build_context({"profile": "custom", "defaults": {"provider": "anthropic", "models": {"openai": {"default": "m"}}},
                                      "stages": [{"id": "implement", "type": "implement", "provider": "openai",
                                                  "backend": {"name": "claude-code-action"}, "model": {"default": "m"}}]}),
        "render: openai implement with explicit claude-code-action backend fails loud",
    )
    # a bare anthropic implement stage with no resolvable model still fails loud on the model.
    expect_raises(
        lambda: render.build_context({"profile": "custom", "defaults": {"provider": "anthropic", "models": {}},
                                      "stages": [{"id": "implement", "type": "implement", "provider": "anthropic"}]}),
        "render: anthropic implement stage fails loud on unresolved model",
    )
    # provider `claude` was renamed to `anthropic` -> rejected with a migration error.
    expect_raises(
        lambda: render.validate_config({"version": 2, "profile": "custom",
                                        "defaults": {"provider": "claude", "models": {"claude": {"default": "c"}}},
                                        "stages": [{"id": "implement", "type": "implement"}]}),
        "validate: renamed provider 'claude' fails loud with a migration error",
    )
    # the standard profile's review/security stages carry provider openai, so the codex review lane
    # renders out of the box (regression: profile review stages must not inherit the anthropic default
    # and silently drop the lane).
    std = render.render_all({"version": 2, "profile": "standard",
                             "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "m"}}}})
    check("request-review.yml" in std and "implementor.yml" in std,
          "select: standard profile renders the implementer + codex review lane out of the box")


def test_round2_fixes() -> None:
    # duplicate explicit stage id -> fail loud
    expect_raises(
        lambda: render.expand_stages({"profile": "custom", "stages": [{"id": "a", "type": "review"}, {"id": "a", "type": "security"}]}),
        "expand_stages: duplicate explicit id fails loud",
    )

    # diamond extends (two bases share an ancestor) must NOT raise circular
    with _project_dir() as dp:
        (dp / "org.yml").write_text("version: 2\ndefaults: {provider: anthropic}\n")
        (dp / "teamA.yml").write_text("version: 2\nextends: org.yml\n")
        (dp / "teamB.yml").write_text("version: 2\nextends: org.yml\n")
        (dp / "repo.yml").write_text("version: 2\nprofile: custom\nextends: [teamA.yml, teamB.yml]\n")
        merged = render.load_config(dp / "repo.yml")
        check(merged["defaults"]["provider"] == "anthropic", "extends: diamond (shared ancestor) resolves, no false cycle")

    # preset pre-fills commands; multiline command indents every line -> valid YAML
    steps = render._build_steps({"build": {"preset": "python"}})
    check("pytest" in steps, "build_steps: preset python pre-fills commands")
    ml = render._build_steps({"build": {"commands": {"test": "echo one\necho two"}}})
    check("\n          echo two" in ml, "build_steps: multiline command lines are all indented")

    # A YAML-keyword branch name (pattern-safe but boolean-like) stays a quoted STRING filter,
    # not the YAML boolean True. (Characters that break quoting are rejected up front — see round-4.)
    import yaml as _yaml
    rendered = render.render_all(
        {"version": 2, "profile": "custom", "platform": {"type": "github", "default_branch": "true"},
         "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "c"}}},
         "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}]},
        "github",
    )
    doc = _yaml.safe_load(rendered["validate.yml"])
    on_block = doc.get("on", doc.get(True))  # YAML parses the `on:` key as boolean True
    check(on_block["push"]["branches"] == ["true"], "render: YAML-keyword default_branch stays a quoted string filter")

    # instructions as a file path is loaded
    inv = build_invocation({"defaults": {"provider": "anthropic"}},
                           {"id": "x", "type": "custom", "provider": "anthropic", "instructions": "stagr/templates/skills/code-review/SKILL.md"}, "m")
    check("Code Review" in inv.system_prompt, "backend: instructions file path is loaded as content")


def test_round3_fixes() -> None:
    from stagr.backends.generic import runner as gen

    # redact_secrets: default true; guardrails toggle propagates to the invocation.
    inv = build_invocation({"defaults": {"provider": "anthropic"}},
                           {"id": "r", "type": "review", "provider": "anthropic"}, "m")
    check(inv.redact_secrets is True, "backend: redact_secrets defaults true")
    inv_off = build_invocation({"defaults": {"provider": "anthropic"}, "guardrails": {"redact_secrets_in_context": False}},
                               {"id": "r", "type": "review", "provider": "anthropic"}, "m")
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
        build_invocation({"defaults": {"provider": "anthropic"}},
                         {"id": "x", "type": "custom", "provider": "anthropic", "instructions": "/etc/passwd"}, "m")
        failures.append("build_invocation must reject an absolute out-of-repo instructions path")
        print("FAIL build_invocation must reject an absolute instructions path", file=sys.stderr)
    except ValueError:
        print("OK  backend: instructions path outside the repo is rejected")

    # inline instructions containing a slash but not a real file stay inline (not treated as a path).
    inv3 = build_invocation({"defaults": {"provider": "anthropic"}},
                            {"id": "x", "type": "custom", "provider": "anthropic",
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
                 "request-review.yml", "final-security-review.yml", "resolve-threads.yml"):
        check(name in rendered, f"select: {name} emitted for codex-review config")
    # The codex PAT is referenced by NAME (from platform.auth.token_secret), never a value.
    check("secrets.REMEDIATION_TOKEN" in rendered["request-review.yml"],
          "select: codex_review_secret NAME substituted into request-review")
    check(not re.search(r"ghp_[A-Za-z0-9]{8,}", rendered["resolve-threads.yml"]),
          "select: resolve-threads inlines no secret value")

    # No codex review stage -> the review lane is NOT emitted (module-aware, not glob-all).
    minimal = {"version": 2, "profile": "custom",
               "platform": {"type": "github", "default_branch": "main"},
               "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "c"}}},
               "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}]}
    r2 = render.render_all(minimal, "github")
    check("request-review.yml" not in r2 and "resolve-threads.yml" not in r2,
          "select: no review lane without a codex review stage")
    check("validate.yml" in r2, "select: core pipeline still emitted")

    # No implement stage -> implementor.yml is NOT emitted (it would carry an empty model and a
    # provider key the graph never uses); the review lane still renders for the review stage.
    review_only = {"version": 2, "profile": "custom",
                   "platform": {"type": "github", "default_branch": "main"},
                   "defaults": {"provider": "openai", "models": {}},
                   "stages": [{"id": "review", "type": "review", "provider": "openai",
                               "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]}]}
    r3 = render.render_all(review_only, "github")
    check("implementor.yml" not in r3, "select: no implementor.yml without an implement stage")
    check("validate.yml" in r3 and "request-review.yml" in r3,
          "select: core + review lane still emitted for a review-only graph")

    # Split lanes: a code-review-only graph renders the on-push code lane (request-review.yml) and
    # NEVER the security lane; the code lane posts only `@codex review`.
    code_only = {"version": 2, "profile": "custom",
                 "platform": {"type": "github", "default_branch": "main"},
                 "defaults": {"provider": "openai", "models": {}},
                 "stages": [{"id": "review", "type": "review", "provider": "openai",
                             "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]}]}
    r_code = render.render_all(code_only, "github")
    check("post_codex '@codex review'" in r_code["request-review.yml"]
          and "@codex security review" not in r_code["request-review.yml"],
          "request-review: posts only the code review, never security")
    check("final-security-review.yml" not in r_code,
          "select: no security lane without a codex security stage")

    # A codex security stage WITHOUT a codex code-review stage is rejected: the security review runs
    # only after the code review converges, so a security-only graph would render a workflow that can
    # never fire. Fail loud at both the render path and the validation front door.
    security_only = {"version": 2, "profile": "custom",
                     "platform": {"type": "github", "default_branch": "main"},
                     "defaults": {"provider": "openai", "models": {}},
                     "stages": [{"id": "security", "type": "security", "provider": "openai",
                                 "backend": {"name": "codex"}, "triggers": ["pr_opened", "pr_updated"]}]}
    expect_raises(lambda: render.render_all(security_only, "github"),
                  "select: codex security stage without a code-review stage fails loud (render)")
    expect_raises(lambda: render.validate_config(security_only),
                  "validate: codex security stage without a code-review stage fails loud (front door)")

    # The dogfood config has a codex security stage -> the security review is requested ONLY from the
    # final-security-review lane (never alongside the code review), so the two never run concurrently.
    check("@codex security review" in rendered["final-security-review.yml"],
          "final-security-review: requests the security review")
    check("@codex security review" not in rendered["request-review.yml"],
          "request-review: never requests the security review (moved to the final lane)")

    # The lane registry is the single selection seam (names, in emit order).
    check([lane.name for lane in render.LANES]
          == ["core", "implementor", "codex-code-review", "codex-security-review", "codex-threads"],
          "select: LANES registry drives template selection, in emit order")


def test_round4_fixes() -> None:
    from stagr.backends.generic import runner as gen

    # S1: cyclic skill extends fails loud instead of RecursionError (use real files as content).
    cyclic_config = {"skills": {
        "a": {"source": "path", "path": "stagr/templates/skills/code-review/SKILL.md", "extends": "b"},
        "b": {"source": "path", "path": "stagr/templates/skills/security-review/SKILL.md", "extends": "a"},
    }}
    try:
        gen.load_skill("a", cyclic_config)
        failures.append("load_skill must reject a skill extends cycle")
        print("FAIL load_skill must reject a skill extends cycle", file=sys.stderr)
    except ValueError:
        print("OK  backend: cyclic skill extends fails loud")

    # S2: unsafe default_branch fails loud; a normal one is fine.
    base = {"version": 2, "profile": "custom", "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "c"}}},
            "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}]}
    expect_raises(lambda: render.build_context({**base, "platform": {"type": "github", "default_branch": 'release"2026'}}),
                  "render: quote in default_branch fails loud")
    ctx = render.build_context({**base, "platform": {"type": "github", "default_branch": "release/2026"}})
    check(ctx["default_branch"] == "release/2026", "render: normal default_branch accepted")
    # git-valid names with '+' or ',' are safe in quoted contexts — accepted, not rejected.
    ctx2 = render.build_context({**base, "platform": {"type": "github", "default_branch": "release+hotfix,2026"}})
    check(ctx2["default_branch"] == "release+hotfix,2026", "render: '+'/',' branch names accepted (serialize-safe)")

    # R8: a mapping `extends` is rejected rather than having its keys iterated as base paths.
    expect_raises(lambda: render.resolve_extends({"extends": {"base.yml": "ignored"}}, REPO_ROOT),
                  "extends: mapping shape fails loud")

    # S-a: a builtin skill id that escapes SKILLS_DIR (absolute / ..) is rejected.
    from stagr.backends.generic import runner as _gen
    try:
        _gen.load_skill("/proc/self/environ", {})
        failures.append("load_skill must confine builtin skill ids to SKILLS_DIR")
        print("FAIL load_skill must confine builtin skill ids", file=sys.stderr)
    except (ValueError, FileNotFoundError):
        print("OK  backend: builtin skill id escaping SKILLS_DIR is rejected")

    # S-b: an implementer model with an expression metacharacter fails loud at render.
    inj = {"version": 2, "profile": "custom", "platform": {"type": "github", "default_branch": "main"},
           "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "m') || secrets.X }}"}}},
           "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}]}
    expect_raises(lambda: render.build_context(inj), "render: unsafe implementer model fails loud")

    # T-b: a model with ':' or '/' that the renderer accepts must also pass the rendered
    # implementor's own runtime model check (aligned allowlists), or the workflow can't run.
    modcfg = {"version": 2, "profile": "custom", "platform": {"type": "github", "default_branch": "main"},
              "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "ns/model:tag"}}},
              "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}]}
    check(render.build_context(modcfg)["implementer_model"] == "ns/model:tag", "render: ':'/'/' model accepted")
    impl_wf = render.render_all(modcfg, "github")["implementor.yml"]
    check("[A-Za-z0-9._:/-]" in impl_wf, "render: implementor runtime model regex matches renderer allowlist")

    # U-c: an agent-preset `from` that escapes the presets dir is rejected (path traversal).
    expect_raises(lambda: render.expand_stages({"profile": "custom",
                  "stages": [{"id": "x", "from": "../../../../etc/passwd"}]}),
                  "expand_stages: preset `from` escaping AGENTS_DIR fails loud")

    # S3: agent contracts are always excluded from the fast path.
    ex = json.loads(ctx["fast_path_exclude_json"])
    check({"AGENTS.md", "CLAUDE.md", "**/AGENTS.md", "**/CLAUDE.md"} <= set(ex), "render: AGENTS/CLAUDE always fast-path-excluded")

    # S3b: routing.fast_path.enabled: false disables the lane — the glob list renders empty, so the
    # rendered router classifies nothing as trivial and routes every PR to the reviewer.
    off = render.build_context({**base, "routing": {"fast_path": {"enabled": False,
                               "globs": ["**/*.md"], "max_files": 20, "max_lines": 200}}})
    check(json.loads(off["fast_path_globs_json"]) == [], "render: fast_path.enabled false empties trivial globs")
    on = render.build_context({**base, "routing": {"fast_path": {"globs": ["**/*.md"]}}})
    check(json.loads(on["fast_path_globs_json"]) == ["**/*.md"], "render: fast_path enabled by default keeps globs")

    # A3: an invalid token_secret name fails loud.
    expect_raises(lambda: render.build_context({**base, "platform": {"type": "github", "default_branch": "main",
                  "auth": {"token_secret": "bad-name"}}}), "render: invalid token_secret name fails loud")

    # A3b: GITHUB_TOKEN (the workflow's own principal, not a real-user PAT) is rejected as token_secret.
    expect_raises(lambda: render.build_context({**base, "platform": {"type": "github", "default_branch": "main",
                  "auth": {"token_secret": "GITHUB_TOKEN"}}}),
                  "render: GITHUB_TOKEN token_secret fails loud (reserved, not a real-user PAT)")

    # A2: narrowed trusted_roles render into the review lane (not a hardcoded allowlist).
    narrow = {"version": 2, "profile": "custom",
              "platform": {"type": "github", "default_branch": "main", "trusted_roles": ["owner"],
                           "auth": {"token_secret": "REMEDIATION_TOKEN"}},
              "defaults": {"provider": "openai", "models": {"openai": {"default": "o"}}},
              "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"}, "triggers": ["pr_updated"]}]}
    rn = render.render_all(narrow, "github")
    check('fromJSON(\'["OWNER"]\')' in rn["request-review.yml"], "render: trusted_roles rendered into request-review (narrowed)")

    # A4: a codex review stage that omits pr_updated does not emit the push-review lane.
    manual = {**narrow, "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"}, "triggers": ["manual"]}]}
    rm = render.render_all(manual, "github")
    check("request-review.yml" not in rm, "render: review lane omitted when stage lacks pr_updated trigger")

    # A5: an enabled budget is carried on the invocation; a disabled one is not.
    inv = build_invocation({"defaults": {"provider": "anthropic"}, "budgets": {"enabled": True, "per_run": {"max_usd": 5}, "on_exceed": "block"}},
                           {"id": "r", "type": "review", "provider": "anthropic"}, "m")
    check(inv.budget.get("enabled") is True and inv.budget.get("on_exceed") == "block", "backend: enabled budget carried")
    inv0 = build_invocation({"defaults": {"provider": "anthropic"}, "budgets": {"enabled": False, "per_run": {"max_usd": 5}}},
                            {"id": "r", "type": "review", "provider": "anthropic"}, "m")
    check(inv0.budget == {}, "backend: disabled budget not carried")
    # stage budget overrides global
    invs = build_invocation({"defaults": {"provider": "anthropic"}, "budgets": {"enabled": True, "per_run": {"max_usd": 5}}},
                            {"id": "r", "type": "review", "provider": "anthropic", "budgets": {"enabled": True, "per_run": {"max_usd": 1}}}, "m")
    check(invs.budget["per_run"]["max_usd"] == 1, "backend: stage budget overrides global")

    # A6: allowed_tools + max_context_files carried on the invocation.
    invg = build_invocation({"defaults": {"provider": "anthropic"}, "guardrails": {"allowed_tools": ["read", "grep"], "max_context_files": 12}},
                            {"id": "r", "type": "review", "provider": "anthropic"}, "m")
    check(invg.allowed_tools == ["read", "grep"] and invg.max_context_files == 12, "backend: tool/context guardrails carried")


def main() -> int:
    test_resolution()
    test_profile_expansion()
    test_backend()
    test_new_behaviors()
    test_round2_fixes()
    test_round3_fixes()
    test_pipeline_selection()
    test_round4_fixes()
    test_render_structural()
    if failures:
        print(f"\n{len(failures)} test failure(s).", file=sys.stderr)
        return 1
    print("\nAll M2 renderer/backend tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
