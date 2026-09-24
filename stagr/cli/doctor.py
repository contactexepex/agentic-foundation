"""`stagr doctor` — validate the config and print the health report."""
from __future__ import annotations

import argparse
import json
import sys

from .. import render
from .report import _load_validated, collect_report


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
    module_summary = ", ".join(f"{name}={value}" for name, value in report["modules"].items()) or "(none)"
    print(f"  modules:        {module_summary}")
    print("  stages:")
    for stage in report["stages"]:
        print(
            f"    - {stage['id']:<16} type={stage['type']:<16} backend={stage['backend']:<16} "
            f"model={stage['model']}"
        )
    print("  secrets required (configure these NAMES; values live in CI secrets, never here):")
    for name in report["secret_names"]:
        print(f"    - {name}")
    print(f"  workflows to render: {', '.join(report['workflows']) or '(none)'}")

    if report["problems"]:
        print("\ndoctor: problems found:", file=sys.stderr)
        for problem in report["problems"]:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\ndoctor: healthy — config resolves and the pipeline renders.")
    return 0
