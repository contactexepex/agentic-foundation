"""`stagr plan` and `stagr apply` — render the pipeline and diff or write it."""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from .. import render
from .report import _load_validated


def _render_or_fail(config_path: Path, platform_override: str | None) -> dict[str, str]:
    cfg, platform = _load_validated(config_path)
    return render.render_all(cfg, platform_override or platform)


def _classify(out_dir: Path, rendered: dict[str, str]) -> list[tuple[str, str]]:
    """Compare rendered output against the target dir: (status, name) per workflow."""
    result: list[tuple[str, str]] = []
    for name, content in sorted(rendered.items()):
        target = out_dir / name
        if not target.exists():
            result.append(("new", name))
        elif target.read_text(encoding="utf-8") == content:
            result.append(("unchanged", name))
        else:
            result.append(("changed", name))
    return result


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        rendered = _render_or_fail(args.config, args.platform)
    except render.RenderError as exc:
        print(f"plan: {exc}", file=sys.stderr)
        return 1
    out_dir = args.out
    print(f"stagr plan — would render {len(rendered)} workflow(s) into {out_dir}/")
    for status, name in _classify(out_dir, rendered):
        marker = {"new": "+ new     ", "changed": "~ changed ", "unchanged": "= unchanged"}[status]
        print(f"  {marker} {name}")
        if status == "changed" and args.diff:
            current = (out_dir / name).read_text(encoding="utf-8").splitlines()
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
        rendered = _render_or_fail(args.config, args.platform)
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
        (out_dir / name).write_text(rendered[name], encoding="utf-8")
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
