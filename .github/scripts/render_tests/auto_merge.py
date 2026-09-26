"""Auto-merge gate: security-focused tests that complement the lane-selection matrix in selection.py.

Covers (Codex plan review v4):
  * the INDEPENDENT templating-safety closure (emitted tokens vs produced/classified, with a regression
    fixture that must fail) — proves no operator string can be templated into a workflow unvalidated;
  * the per-field `${{ }}` expression-injection matrix (reject at render AND the config front door);
  * the P0 workflow-security invariants (pull_request_target, no checkout, least privilege, SHA-pinned
    merge, no persistent status);
  * the build-command trust boundary (operator `${{ }}` survives; the renderer injects no PR data).
"""
from __future__ import annotations

import copy
import re

from .harness import REPO_ROOT, check, expect_raises, render

WF_DIR = REPO_ROOT / "stagr" / "templates" / "workflows" / "github"

# A blocking codex review+security graph with auto_merge on and fast path off (the fully-featured gate).
_BASE = {
    "version": 2, "profile": "custom",
    "platform": {"type": "github", "default_branch": "main", "auth": {"token_secret": "REMEDIATION_TOKEN"}},
    "defaults": {"provider": "openai", "models": {}},
    "modules": {"auto_merge": True},
    "routing": {"fast_path": {"enabled": False}},
    "stages": [
        {"id": "review", "type": "review", "backend": {"name": "codex"}, "gate": "blocking",
         "triggers": ["pr_opened", "pr_updated"]},
        {"id": "security", "type": "security", "backend": {"name": "codex"}, "gate": "blocking",
         "triggers": ["pr_opened", "pr_updated"]},
    ],
}
# An implement-only graph (no codex review required), so the fast path may be ON — used for glob cases.
_IMPL_BASE = {
    "version": 2, "profile": "custom",
    "platform": {"type": "github", "default_branch": "main"},
    "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "c"}}},
    "modules": {"auto_merge": True},
    "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}],
}


def _with(base: dict, **over: object) -> dict:
    cfg = copy.deepcopy(base)
    cfg.update(copy.deepcopy(over))
    return cfg


def _closure_report(emitted: set[str], produced: set[str], operator: set[str],
                    safe: set[str], nonop: set[str]) -> list[tuple[str, list[str]]]:
    """Pure closure check (so a regression fixture can prove it has teeth). Returns the violations."""
    issues: list[tuple[str, list[str]]] = []
    if emitted - produced:
        issues.append(("emitted_but_not_produced", sorted(emitted - produced)))
    if produced != (safe | nonop):
        issues.append(("unclassified_token", sorted(produced ^ (safe | nonop))))
    if operator != safe:
        issues.append(("provenance_ne_declared_safe_literal", sorted(operator ^ safe)))
    if not safe.isdisjoint(nonop):
        issues.append(("classes_overlap", sorted(safe & nonop)))
    return issues


def test_auto_merge_templating_closure() -> None:
    ctx = render.build_context(_BASE)
    produced = {rv.token for rv in ctx.entries}
    operator = {rv.token for rv in ctx.entries if rv.operator_controlled}
    safe = set(render.SAFE_LITERAL_TOKENS)
    nonop = set(render.NON_OPERATOR_TOKENS)
    emitted: set[str] = set()
    for tpl in WF_DIR.glob("*.tmpl"):
        emitted |= render.emitted_tokens(tpl.read_text(encoding="utf-8"))

    check(_closure_report(emitted, produced, operator, safe, nonop) == [],
          "closure: emitted tokens produced, every token classified, provenance == declared safe-literals")
    # render_template still rejects an unknown token outright.
    expect_raises(lambda: render.render_template("a {{ not_a_token }} b", ctx.substitutions()),
                  "closure: render_template rejects an unregistered token")


def test_auto_merge_injection_matrix() -> None:
    expr = "${{ github.token }}"
    plat = _BASE["platform"]
    # (name, config) — each must be rejected at BOTH render and the front door.
    cases = [
        ("human_merge_label", _with(_BASE, platform={**plat, "labels": {"human_merge": expr}})),
        ("dispatch_label", _with(_BASE, platform={**plat, "labels": {"dispatch": expr}})),
        ("default_branch", _with(_BASE, platform={**plat, "default_branch": expr})),
        ("token_secret", _with(_BASE, platform={**plat, "auth": {"token_secret": expr}})),
        ("check_name", _with(_BASE, merge={"required_status_checks": [{"name": expr, "app_id": 1}]})),
        ("fast_path_globs", _with(_IMPL_BASE, routing={"fast_path": {"enabled": True, "globs": [expr]}})),
        ("fast_path_exclude", _with(_IMPL_BASE, routing={"fast_path": {"enabled": False, "exclude": [expr]}})),
    ]
    for name, cfg in cases:
        expect_raises(lambda c=cfg: render.render_all(c, "github"),
                      f"injection: {name} ${{}} expression rejected at render")
        expect_raises(lambda c=cfg: render.validate_config(c),
                      f"injection: {name} ${{}} expression rejected at front door")
    # Implementer model (needs an implement stage; validated by the model regex).
    modcfg = _with(_IMPL_BASE, defaults={"provider": "anthropic", "models": {"anthropic": {"default": expr}}})
    expect_raises(lambda: render.render_all(modcfg, "github"),
                  "injection: implementer model ${{}} expression rejected at render")


def test_auto_merge_config_hardening() -> None:
    # protected_paths are matched by a literal bash glob and single-quoted in YAML: a brace (silently
    # unmatched -> weakened guard) or single quote (breaks the scalar) must be rejected (render + front door).
    for bad in ("**/*.{yml,yaml}", "docs/team's/**"):
        cfg = _with(_IMPL_BASE, merge={"protected_paths": [bad]})
        expect_raises(lambda c=cfg: render.render_all(c, "github"),
                      f"protected_paths: {bad!r} rejected at render")
        expect_raises(lambda c=cfg: render.validate_config(c),
                      f"protected_paths: {bad!r} rejected at front door")
    # Protected paths support ONLY exact paths and 'dir/**' prefixes (matched deterministically); general
    # globs are rejected because bash cannot reliably match '**' (a '**/*.yml' would miss a root-level file).
    ok = render.render_all(_with(_IMPL_BASE, merge={"protected_paths": ["config/**", "infra/main.tf"]}), "github")["auto-merge.yml"]
    check('"config/**"' in ok and '"infra/main.tf"' in ok, "protected_paths: dir/** prefix + exact path render")
    for bad in ("**/*.yml", "src/*", "a/**/b", "?.yml"):
        cfg = _with(_IMPL_BASE, merge={"protected_paths": [bad]})
        expect_raises(lambda c=cfg: render.render_all(c, "github"),
                      f"protected_paths: general glob {bad!r} rejected at render")
        expect_raises(lambda c=cfg: render.validate_config(c),
                      f"protected_paths: general glob {bad!r} rejected at front door")

    # RenderContext is the exported public API (build_context, via stagr/render/__init__.py).
    # Operators and downstream code use it; exercise the Mapping contract so regressions in
    # indexing, iteration, or equality are caught before they ship.
    ctx = render.build_context(_IMPL_BASE)
    subs = ctx.substitutions()
    check(ctx["human_merge_label"] == subs["human_merge_label"], "RenderContext: indexing works")
    check("human_merge_label" in ctx and ctx.get("nope") is None, "RenderContext: membership + .get() work")
    check(dict(ctx.items()) == subs and set(ctx.keys()) == set(subs) and len(ctx) == len(subs),
          "RenderContext: .items()/.keys()/len() match substitutions()")
    check(sorted(ctx.values()) == sorted(subs.values()), "RenderContext: .values() returns the value strings")
    check(ctx == subs and ctx == render.build_context(_IMPL_BASE),
          "RenderContext: == compares by mapping value (dataclass eq disabled)")
    check(any(rv.token == "human_merge_label" and rv.operator_controlled for rv in ctx.entries),
          "RenderContext: .entries exposes per-value provenance")


def test_auto_merge_p0_invariants() -> None:
    am = render.render_all(_BASE, "github")["auto-merge.yml"]
    check("pull_request_target" in am, "P0: gate runs on pull_request_target")
    check("\n  pull_request:\n" not in am, "P0: gate never runs on a pull_request trigger")
    check("actions/checkout" not in am and "checkout@" not in am, "P0: gate never checks out PR content")
    check("uses: ./" not in am, "P0: gate invokes no local action from the repo")
    check('-f sha="$GATE_HEAD"' in am, "P0: merge is pinned to the evaluated head SHA")
    for perm in ("contents: write", "pull-requests: write", "checks: read", "statuses: read", "actions: read"):
        check(perm in am, f"P0: least-privilege permission '{perm}' present")
    check("id-token:" not in am and "issues: write" not in am and "packages:" not in am,
          "P0: no excess permissions granted")
    # Self-merge model: the gate publishes NO commit status (no forgeable persistent positive artifact).
    check("/statuses/" not in am and "--method POST" not in am,
          "P0: gate publishes no commit status (no rollup to go stale or be forged)")
    # Sweep fairness (#33): the whole-repo sweep lists open PRs oldest-updated-first so an older
    # ready PR is not starved when many PRs are open and one sweep run exhausts its budget.
    check("-f sort=updated -f direction=asc" in am,
          "P0: sweep lists open PRs oldest-updated-first (starvation-resistant ordering)")


def test_build_command_trust_boundary() -> None:
    sentinel = "SENTINEL_build_cmd_9f3a2b"
    cfg = _with(
        _IMPL_BASE,
        build={"commands": {"install": f"echo {sentinel} && pip install -r req.txt",
                            "test": "pytest -q  # auth: ${{ secrets.NPM_TOKEN }}"}},
    )
    validate = render.render_all(cfg, "github")["validate.yml"]
    # Operator build commands (trusted shell) flow through verbatim, incl. a legitimate ${{ secrets.* }}.
    check(sentinel in validate, "build-cmd: operator command text flows into the build step")
    check("${{ secrets.NPM_TOKEN }}" in validate,
          "build-cmd: a ${{ secrets.* }} expression survives rendering unchanged (trusted shell)")
    # The renderer injects NO untrusted PR data into the build STEP: it cannot, since build_steps is a pure
    # function of build.commands. Isolate the build run-block (the one carrying our command text) and assert
    # no PR-context expression appears there. (validate.yml's own triggers reference the PR event — that is
    # the trusted workflow scaffold, not the build step, so scope the check to the build block.)
    blocks = re.findall(r"run: \|\n((?:[ \t].*\n?)+)", validate)
    build_block = next((b for b in blocks if sentinel in b), "")
    check(bool(build_block), "build-cmd: located the build run-block")
    for pr_field in ("github.event.pull_request", "github.head_ref", "github.event.issue", "github.actor",
                     "github.event.comment", "github.event.review"):
        check(pr_field not in build_block,
              f"build-cmd: no untrusted PR field ({pr_field}) is injected into the build step")
