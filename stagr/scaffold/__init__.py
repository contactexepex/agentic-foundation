"""Config scaffolding for `stagr init` — generate a commented `.agentic/config.yml`.

Two onboarding paths share this module:
  * a template generated non-interactively from a profile (`stagr init --profile standard`), and
  * an interactive wizard (`stagr init`) that collects a few choices, then renders the same template.

The output is YAML *with comments* (each section says what it is, its default, and how it is used),
kept concise so the file stays mostly content. Comments are why the generator emits text directly
rather than `yaml.dump` (which drops comments). Every generated profile validates against the schema
and renders, which the tests assert.

This package was split from a single `scaffold.py` module into cohesive submodules; this `__init__`
re-exports every top-level name so `from stagr import scaffold; scaffold.<name>` keeps working
unchanged.
"""
from __future__ import annotations

from .detect import (
    BUILD_PRESETS,
    CUSTOM_PRESET,
    _BUILD_PRESET_OPTIONS,
    _PRESET_SIGNALS,
    _schema_build_presets,
    _signal_present,
    detect_build_preset,
)
from .defaults import (
    DEFAULT_BRANCH,
    DEFAULT_MODEL,
    DEFAULT_PLATFORM,
    PROFILES,
    _DOCS_BASE,
    _DOCS_CHARTER,
    _DOCS_CONFIG,
    _PROFILE_STAGES,
    _ROADMAP_STAGE_PROVIDER,
    _ROADMAP_STAGES,
    _canonical_gate,
    _profile_security_blocking,
    default_choices,
)
from .snippets import (
    _CUSTOM_SKELETON,
    _IMPLEMENT_SNIPPET,
    _review_snippet,
    _security_snippet,
    _stages_block,
)
from .generate import generate
from .wizard import (
    _ask,
    run_wizard,
)
