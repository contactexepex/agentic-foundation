#!/usr/bin/env python3
"""stagr — the agentic-foundation control plane CLI (M3).

Three subcommands over the M2 renderer core (`render.py`), so newcomers can adopt the
toolkit with one command and experts can inspect exactly what it will do first:

    stagr doctor   # validate config + resolve the graph; report health, secrets (by NAME), lanes
    stagr plan     # dry run: show what apply WOULD write to .github/workflows (no writes)
    stagr apply    # render the pipeline and write it (idempotent; never deletes unless --prune)

Design invariants (shared with the renderer):
  * No network. No secret VALUES are ever read, printed, or logged — only the secret NAMES
    the contract references, so an operator knows what to configure.
  * Fail loud: a config that does not resolve (schema, semantics, or an unresolvable model)
    exits non-zero with a precise message rather than emitting a broken pipeline.
  * Deterministic and idempotent: apply writes only files whose content changed.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

from . import render
from .backends.generic.runner import DEFAULT_KEY_SECRET


# --------------------------------------------------------------------------- helpers


def _stage_provider(cfg: dict[str, Any], stage: dict[str, Any]) -> str | None:
    return stage.get("provider") or (cfg.get("defaults", {}) or {}).get("provider")


def _key_secret_name(cfg: dict[str, Any], provider: str) -> str:
    providers = cfg.get("providers", {}) or {}
    return (providers.get(provider, {}) or {}).get(
        "api_key_secret", DEFAULT_KEY_SECRET.get(provider, "MODEL_API_KEY")
    )


def collect_report(cfg: dict[str, Any], platform: str) -> dict[str, Any]:
    """Resolve the config into a structured, secret-free health report.

    Returns model resolution per stage (or the reason it is app-supplied / unresolved),
    the set of secret NAMES the pipeline needs, the enabled modules, and the workflow
    files that would be rendered. Never contains a secret value.
    """
    stages = render.expand_stages(cfg)
    plat = cfg.get("platform", {}) or {}
    report: dict[str, Any] = {
        "profile": cfg.get("profile", "standard"),
        "platform": platform,
        "default_branch": plat.get("default_branch", "main"),
        "trusted_roles": plat.get("trusted_roles", ["owner", "member", "collaborator"]),
        "modules": cfg.get("modules", {}) or {},
        "stages": [],
        "secret_names": [],
        "workflows": [],
        "problems": [],
    }

    secret_names: set[str] = set()
    for stage in stages:
        backend = render._stage_backend(stage)
        provider = _stage_provider(cfg, stage)
        entry: dict[str, Any] = {
            "id": stage.get("id"),
            "type": stage.get("type", "custom"),
            "backend": backend,
            "provider": provider,
            "gate": stage.get("gate"),
            "skill": stage.get("skill"),
        }
        # Resolve the model only for backends that consume one; app backends supply their own.
        if backend in render.BACKENDS_NEEDING_MODEL:
            try:
                entry["model"] = render.resolve_model(cfg, stage, "standard")
            except render.RenderError as exc:
                entry["model"] = None
                report["problems"].append(f"stage '{stage.get('id')}': {exc}")
        else:
            entry["model"] = f"(app-supplied by backend '{backend}')"
        # Record the secret NAME this stage's provider needs (never a value).
        if provider:
            secret_names.add(_key_secret_name(cfg, provider))
            extra = ((cfg.get("providers", {}) or {}).get(provider, {}) or {}).get("extra_headers_secret")
            if extra:
                secret_names.add(extra)
        report["stages"].append(entry)

    # The codex review lane authors comments/resolutions with a real-user PAT (NAME only).
    if any(s.get("type") in {"review", "security"} and render._stage_backend(s) == "codex" for s in stages):
        secret_names.add(((plat.get("auth", {}) or {}).get("token_secret")) or "CODEX_REMEDIATION_TOKEN")

    report["secret_names"] = sorted(secret_names)
    try:
        report["workflows"] = sorted(render.render_all(cfg, platform).keys())
    except render.RenderError as exc:
        report["problems"].append(f"render: {exc}")
    return report


def _load_validated(config_path: Path) -> tuple[dict[str, Any], str]:
    cfg = render.load_config(config_path)
    render.validate_config(cfg)
    platform = (cfg.get("platform", {}) or {}).get("type", "github")
    return cfg, platform


# --------------------------------------------------------------------------- doctor


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        cfg, platform = _load_validated(args.config)
    except render.RenderError as exc:
        print(f"doctor: config is invalid: {exc}", file=sys.stderr)
        return 1
    platform = args.platform or platform
    report = collect_report(cfg, platform)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if report["problems"] else 0

    print(f"stagr doctor — {args.config}")
    print(f"  profile:        {report['profile']}")
    print(f"  platform:       {report['platform']} (default branch: {report['default_branch']})")
    print(f"  trusted roles:  {', '.join(report['trusted_roles'])}")
    mods = ", ".join(f"{k}={v}" for k, v in report["modules"].items()) or "(none)"
    print(f"  modules:        {mods}")
    print("  stages:")
    for s in report["stages"]:
        print(
            f"    - {s['id']:<16} type={s['type']:<16} backend={s['backend']:<16} "
            f"model={s['model']}"
        )
    print("  secrets required (configure these NAMES; values live in CI secrets, never here):")
    for name in report["secret_names"]:
        print(f"    - {name}")
    print(f"  workflows to render: {', '.join(report['workflows']) or '(none)'}")

    if report["problems"]:
        print("\ndoctor: problems found:", file=sys.stderr)
        for p in report["problems"]:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("\ndoctor: healthy — config resolves and the pipeline renders.")
    return 0


# ----------------------------------------------------------------------- plan / apply


def _render_or_fail(config_path: Path, platform_override: str | None) -> tuple[dict[str, str], Path]:
    cfg, platform = _load_validated(config_path)
    platform = platform_override or platform
    return render.render_all(cfg, platform), Path()


def _classify(out_dir: Path, rendered: dict[str, str]) -> list[tuple[str, str]]:
    """Compare rendered output against the target dir: (status, name) per workflow."""
    result: list[tuple[str, str]] = []
    for name, content in sorted(rendered.items()):
        target = out_dir / name
        if not target.exists():
            result.append(("new", name))
        elif target.read_text() == content:
            result.append(("unchanged", name))
        else:
            result.append(("changed", name))
    return result


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        rendered, _ = _render_or_fail(args.config, args.platform)
    except render.RenderError as exc:
        print(f"plan: {exc}", file=sys.stderr)
        return 1
    out_dir = args.out
    print(f"stagr plan — would render {len(rendered)} workflow(s) into {out_dir}/")
    for status, name in _classify(out_dir, rendered):
        marker = {"new": "+ new     ", "changed": "~ changed ", "unchanged": "= unchanged"}[status]
        print(f"  {marker} {name}")
        if status == "changed" and args.diff:
            current = (out_dir / name).read_text().splitlines()
            new = rendered[name].splitlines()
            for line in difflib.unified_diff(current, new, fromfile=f"a/{name}", tofile=f"b/{name}", lineterm=""):
                print(f"      {line}")
    # Orphans: workflow files present in the target that this config would NOT render.
    orphans = _orphans(out_dir, rendered)
    if orphans:
        print("  workflows in the target that this config does not render (left untouched; --prune to remove on apply):")
        for name in orphans:
            print(f"      ? {name}")
    print("\nplan: dry run only — nothing was written.")
    return 0


def _orphans(out_dir: Path, rendered: dict[str, str]) -> list[str]:
    if not out_dir.is_dir():
        return []
    present = {p.name for p in out_dir.glob("*.yml")}
    return sorted(present - set(rendered))


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        rendered, _ = _render_or_fail(args.config, args.platform)
    except render.RenderError as exc:
        print(f"apply: {exc}", file=sys.stderr)
        return 1
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for status, name in _classify(out_dir, rendered):
        if status == "unchanged":
            print(f"  = unchanged {name}")
            continue
        (out_dir / name).write_text(rendered[name])
        written += 1
        print(f"  {'+ wrote    ' if status == 'new' else '~ updated  '} {name}")

    orphans = _orphans(out_dir, rendered)
    for name in orphans:
        if args.prune:
            (out_dir / name).unlink()
            print(f"  - pruned   {name}")
        else:
            print(f"  ? kept     {name} (not rendered by this config; --prune to remove)")
    print(f"\napply: {written} file(s) written, {len(rendered) - written} unchanged"
          + (f", {len(orphans)} orphan(s) pruned" if args.prune else ""))
    return 0


# ----------------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="stagr", description="stagr — the agentic-foundation control plane CLI.")
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", default=Path(".agentic/config.yml"), type=Path,
                       help="path to the .agentic/config.yml contract")
        p.add_argument("--platform", default=None, help="override platform.type (e.g. github)")

    d = sub.add_parser("doctor", help="validate config + report health, secrets (by NAME), and lanes")
    common(d)
    d.add_argument("--json", action="store_true", help="emit the report as JSON")
    d.set_defaults(func=cmd_doctor)

    p = sub.add_parser("plan", help="dry run: show what apply would write (no writes)")
    common(p)
    p.add_argument("--out", default=Path(".github/workflows"), type=Path, help="target workflow dir")
    p.add_argument("--diff", action="store_true", help="show a unified diff for changed workflows")
    p.set_defaults(func=cmd_plan)

    a = sub.add_parser("apply", help="render the pipeline and write it (idempotent)")
    common(a)
    a.add_argument("--out", default=Path(".github/workflows"), type=Path, help="target workflow dir")
    a.add_argument("--prune", action="store_true",
                   help="also delete workflow files in the target that this config does not render")
    a.set_defaults(func=cmd_apply)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
