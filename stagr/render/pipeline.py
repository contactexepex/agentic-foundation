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
from .util import _confine_to_project_root, confine_config_path


def render_all(cfg: dict[str, Any], platform: str = "github") -> dict[str, str]:
    tpl_dir = TEMPLATE_ROOT / platform
    if not tpl_dir.is_dir():
        raise RenderError(f"no templates for platform '{platform}' ({tpl_dir})")
    context = build_context(cfg).substitutions()
    selected = select_templates(list(expand_stages(cfg)), cfg)
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
        # Confine the CLI-supplied output dir to the project root, exactly as `--config` is confined:
        # `--out` is an untrusted path and stagr must only ever write inside the repository it operates
        # on (a `../../…`, absolute, or symlink-escaping value is a mistake or a path-traversal attempt).
        # Only when we will actually write: in `--print` mode nothing is written and `--out` is ignored,
        # so validating it there would wrongly fail a non-writing preview.
        out_dir = _confine_to_project_root(args.out, "output dir") if (args.out and not args.print) else None
    except RenderError as exc:
        print(f"render error: {exc}", file=sys.stderr)
        return 1

    if args.print or out_dir is None:
        for name, content in rendered.items():
            print(f"# ===== {name} =====")
            print(content)
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (out_dir / name).write_text(content, encoding="utf-8")
        print(f"wrote {out_dir / name}")
    return 0
