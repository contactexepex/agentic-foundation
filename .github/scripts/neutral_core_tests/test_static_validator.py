"""Re-exports the static validator tests (V-S07, V-S08, V-S09) for the test runner.

The tests live in the static_validator_tests sub-package, split by validation check.
The runner (test_neutral_core_models.py) needs only ``STATIC_VALIDATOR_TESTS``.
"""
from __future__ import annotations

from neutral_core_tests.static_validator_tests import STATIC_VALIDATOR_TESTS

__all__ = ["STATIC_VALIDATOR_TESTS"]
