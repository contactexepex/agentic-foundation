"""Stage signal runtime test sub-package (issue #206).

``STAGE_SIGNAL_TESTS`` is collected by discovery instead of an explicit import list: every
``test_*`` function defined in a ``test_*`` module of this package is registered, so a new test
can never be silently left out of the run. The top-level runner appends the list to ``_TESTS``.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Callable


def _discover_tests() -> list[Callable[[], None]]:
    discovered: list[Callable[[], None]] = []
    for module_info in sorted(pkgutil.iter_modules(__path__), key=lambda info: info.name):
        if not module_info.name.startswith("test_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        discovered.extend(
            function
            for name, function in vars(module).items()
            if name.startswith("test_")
            and inspect.isfunction(function)
            and function.__module__ == module.__name__
        )
    return discovered


STAGE_SIGNAL_TESTS = _discover_tests()
