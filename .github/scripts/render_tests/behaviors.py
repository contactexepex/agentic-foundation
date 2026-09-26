"""Renderer behavior tests: extends, presets, fail-loud guards, and round 2-4 fixes."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from .harness import (
    REPO_ROOT,
    _project_dir,
    build_invocation,
    check,
    expect_raises,
    failures,
    render,
)


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

    # A2: narrowed trusted_roles render into the review lane (not a hardcoded allowlist). The on-push
    # lane enforces the trusted-author guard in-script (the job-level `if:` was removed so the
    # issue_comment/check_suite re-trigger events, whose PR fields are null, still run), so the roles
    # render as the TRUSTED_ROLES env consumed by jq rather than a `fromJSON(...)` expression.
    narrow = {"version": 2, "profile": "custom",
              "platform": {"type": "github", "default_branch": "main", "trusted_roles": ["owner"],
                           "auth": {"token_secret": "REMEDIATION_TOKEN"}},
              "defaults": {"provider": "openai", "models": {"openai": {"default": "o"}}},
              "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"}, "triggers": ["pr_updated"]}]}
    rn = render.render_all(narrow, "github")
    check("TRUSTED_ROLES: '[\"OWNER\"]'" in rn["request-review.yml"]
          and '"MEMBER"' not in rn["request-review.yml"],
          "render: trusted_roles rendered into request-review (narrowed)")

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


def test_budgets_max_review_iterations() -> None:
    # #35: budgets.max_review_iterations declares the review→fix loop cap (enforcement is separate).
    base = {"version": 2, "profile": "standard",
            "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "m"}}}}
    # accepted: a positive integer
    accepted = True
    try:
        render.validate_config({**base, "budgets": {"max_review_iterations": 3}})
    except Exception:
        accepted = False
    check(accepted, "validate: budgets.max_review_iterations accepts a positive integer")
    # rejected: zero, negative, non-integer number, and non-number
    for bad in (0, -1, 1.5, "3"):
        expect_raises(
            lambda b=bad: render.validate_config({**base, "budgets": {"max_review_iterations": b}}),
            f"validate: budgets.max_review_iterations rejects {bad!r}",
        )
