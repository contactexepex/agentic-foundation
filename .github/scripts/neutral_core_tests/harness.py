"""Shared harness for neutral-core model tests.

Owns the single ``failures`` list, the repo-root ``sys.path`` setup, and the
``_fail``/``_ok`` helpers. Every test module and the runner import from here so
all failure records land in one list regardless of which module records them.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

failures: list[str] = []


def _fail(name: str, exc: Exception) -> None:
    failures.append(name)
    print(f"FAIL  {name}")
    traceback.print_exc()
    print()


def _ok(name: str) -> None:
    print(f"ok    {name}")
