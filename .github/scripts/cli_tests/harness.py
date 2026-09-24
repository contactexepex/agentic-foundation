"""Shared harness for the M3 CLI tests.

Owns the single ``failures`` list (mutated in place by ``check``, read by the runner),
the repo-root ``sys.path`` setup, the ``stagr`` imports every test module needs, the
``SECRET_VALUE`` matcher, and the ``_project_dir`` contextmanager. Every test module and
the runner import from here, so all appends land in one list regardless of caller.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from stagr import cli  # noqa: E402
from stagr import render  # noqa: E402

failures: list[str] = []
SECRET_VALUE = re.compile(r"sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}")


@contextmanager
def _project_dir():
    """A temp dir that is also the CWD for the block.

    stagr confines the config file, its extends bases, and init's write destination to the project
    root (the CWD), so a test that exercises those write/read paths must run from inside a project
    checkout (a real operator runs stagr from their repo).
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
