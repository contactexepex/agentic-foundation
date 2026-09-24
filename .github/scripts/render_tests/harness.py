"""Shared harness for the M2 renderer/backend tests.

Owns the single ``failures`` list (mutated in place by ``check``/``expect_raises``, read
by the runner), the repo-root ``sys.path`` setup, the ``stagr`` imports every test module
needs, and the ``_project_dir`` contextmanager. Every test module and the runner import
from here, so all appends land in one list regardless of caller.
"""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
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
