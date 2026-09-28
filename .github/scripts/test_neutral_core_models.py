#!/usr/bin/env python3
"""Tests for neutral core data models and enumerations (Group A: issues #173–#178).

Run with: python .github/scripts/test_neutral_core_models.py
No pytest required. Exit 0 = all pass.

This is a thin runner. The tests live in scoped modules under ``neutral_core_tests/``,
all sharing the single ``failures`` list defined in ``neutral_core_tests.harness``.
Run as a script, ``sys.path[0]`` is ``.github/scripts``, so ``neutral_core_tests``
resolves as a package.
"""
from __future__ import annotations

import sys

from neutral_core_tests.harness import _fail, _ok, failures
from neutral_core_tests.test_enums import test_enum_string_values
from neutral_core_tests.test_normalized_stage import (
    test_normalized_stage_construction,
    test_normalized_stage_empty_dependencies,
)
from neutral_core_tests.test_execution_plan import (
    test_execution_plan_requires_gate_disposition,
    test_execution_plan_valid,
    test_invocation_params_deep_immutable,
    test_invocation_params_immutable,
)
from neutral_core_tests.test_evidence_and_gate import test_evidence_spec_construction
from neutral_core_tests.test_stage_result import (
    test_stage_result_signal_requires_head_sha,
    test_stage_result_spec_construction,
)
from neutral_core_tests.test_render_context import (
    test_render_context_construction,
    test_render_context_is_immutable,
)

_TESTS = [
    test_enum_string_values,
    test_normalized_stage_construction,
    test_normalized_stage_empty_dependencies,
    test_invocation_params_immutable,
    test_invocation_params_deep_immutable,
    test_execution_plan_requires_gate_disposition,
    test_execution_plan_valid,
    test_evidence_spec_construction,
    test_stage_result_signal_requires_head_sha,
    test_stage_result_spec_construction,
    test_render_context_construction,
    test_render_context_is_immutable,
]

if __name__ == "__main__":
    for t in _TESTS:
        try:
            t()
            _ok(t.__name__)
        except Exception as exc:
            _fail(t.__name__, exc)

    if failures:
        print(f"\n{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print(f"\n{len(_TESTS)} tests passed.")
