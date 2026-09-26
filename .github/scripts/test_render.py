#!/usr/bin/env python3
"""Tests for the M2 renderer + generic backend.

Runnable with plain `python .github/scripts/test_render.py` (no pytest needed).
Covers: model-resolution precedence/alias/fail-loud, profile expansion, generic
backend assembly (secret-by-name, no secret values, action mapping), and STRUCTURAL
validity + determinism of the rendered GitHub workflows. Exit 0 = pass.

This is a thin runner: the tests live in scoped modules under `render_tests/`, all
sharing the single `failures` list defined in `render_tests.harness`. Run as a script,
`sys.path[0]` is `.github/scripts`, so `render_tests` resolves as a package.
"""
from __future__ import annotations

import sys

from render_tests.harness import failures
from render_tests.resolution import test_backend, test_profile_expansion, test_resolution
from render_tests.structural import test_render_structural
from render_tests.behaviors import (
    test_new_behaviors,
    test_round2_fixes,
    test_round3_fixes,
    test_round4_fixes,
)
from render_tests.selection import test_pipeline_selection
from render_tests.auto_merge import (
    test_auto_merge_config_hardening,
    test_auto_merge_injection_matrix,
    test_auto_merge_p0_invariants,
    test_auto_merge_templating_closure,
    test_build_command_trust_boundary,
)
from render_tests.gate_behavior import test_gate_behavior
from render_tests.permissions import test_least_privilege_permissions


def main() -> int:
    test_resolution()
    test_profile_expansion()
    test_backend()
    test_new_behaviors()
    test_round2_fixes()
    test_round3_fixes()
    test_pipeline_selection()
    test_round4_fixes()
    test_auto_merge_templating_closure()
    test_auto_merge_injection_matrix()
    test_auto_merge_config_hardening()
    test_auto_merge_p0_invariants()
    test_build_command_trust_boundary()
    test_gate_behavior()
    test_render_structural()
    test_least_privilege_permissions()
    if failures:
        print(f"\n{len(failures)} test failure(s).", file=sys.stderr)
        return 1
    print("\nAll M2 renderer/backend tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
