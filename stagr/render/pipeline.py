"""Top-level rendering and CLI entry point: render every selected template for a platform and
provide `main` for `python -m stagr.render`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .config import load_config, validate_config
from .constants import TEMPLATE_ROOT
from .context import build_context, render_template
from .errors import RenderError
from .lanes import select_templates
from .stages import expand_stages
from .util import confine_config_path


def render_all(cfg: dict[str, Any], platform: str = "github") -> dict[str, str]:
    tpl_dir = TEMPLATE_ROOT / platform
    if not tpl_dir.is_dir():
        raise RenderError(f"no templates for platform '{platform}' ({tpl_dir})")
    context = build_context(cfg)
    selected = select_templates(list(expand_stages(cfg)))
    out: dict[str, str] = {}
    for name in selected:
        tpl = tpl_dir / name
        if not tpl.is_file():
            raise RenderError(f"selected template '{name}' not found in {tpl_dir}")
        out[name[: -len(".tmpl")]] = render_template(tpl.read_text(encoding="utf-8"), context)
    if not out:
        raise RenderError(f"no templates selected for platform '{platform}'")
    return out


# ----------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the agentic-foundation pipeline.")
    parser.add_argument("--config", default=".agentic/config.yml", type=Path)
    parser.add_argument("--out", type=Path, help="output dir (e.g. .github/workflows)")
    parser.add_argument("--print", action="store_true", help="print to stdout, write nothing")
    parser.add_argument("--platform", default=None, help="override platform.type")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(confine_config_path(args.config))
        validate_config(cfg)
        platform = args.platform or (cfg.get("platform", {}) or {}).get("type", "github")
        rendered = render_all(cfg, platform)
    except RenderError as exc:
        print(f"render error: {exc}", file=sys.stderr)
        return 1

    if args.print or not args.out:
        for name, content in rendered.items():
            print(f"# ===== {name} =====")
            print(content)
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (args.out / name).write_text(content, encoding="utf-8")
        print(f"wrote {args.out / name}")
    return 0
