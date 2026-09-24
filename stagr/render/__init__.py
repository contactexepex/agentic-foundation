"""stagr — GitHub pipeline renderer (M2).

Reads a repository's `.agentic/config.yml`, resolves it against the contract
(`stagr/config.schema.json`), and renders the platform pipeline from the
tokenized templates in `stagr/templates/workflows/<platform>/` into `.github/workflows/`.

Design notes
------------
- Deterministic: same config + templates -> byte-identical output.
- No network, no secrets. Secrets are referenced by NAME only.
- Provider/model resolution is the reusable core (M3's doctor/plan/apply import it):
  per-stage, per-tier, precedence per-request > stage > org/account default, with
  `models.aliases` expansion, and FAIL-LOUD if nothing resolves (no hidden default).
- `extends`, `from`-presets, and skills-registry resolution happen before rendering so
  the rendered pipeline reflects the fully-merged contract.

CLI:
    python -m stagr.render --config .agentic/config.yml --out .github/workflows
    python -m stagr.render --config .agentic/config.yml --print

This package was split from a single `render.py` module into cohesive submodules; this
`__init__` re-exports every top-level name so `from stagr import render; render.<name>`
keeps working unchanged.
"""
from __future__ import annotations

from .constants import (
    AGENTS_DIR,
    BACKEND_CLAUDE_ACTION,
    BACKEND_CODEX,
    BACKEND_GENERIC,
    BACKENDS_NEEDING_MODEL,
    DEFAULT_TOKEN_SECRET,
    GATE_ADVISORY,
    GATE_BLOCKING,
    GITHUB_ROLE_MAP,
    MANDATORY_FAST_PATH_EXCLUDE,
    PKG_ROOT,
    PRESET_COMMANDS,
    PROFILE_STAGES,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_TOOL,
    RENAMED_ANTHROPIC_PROVIDER,
    REVIEW_LANE_TYPES,
    SCHEMA_PATH,
    TEMPLATE_ROOT,
)
from .errors import RenderError
from .util import (
    _MODEL_SAFE,
    _SECRET_NAME,
    _UNSAFE_REF,
    _URI_SCHEME,
    _confine_to_project_root,
    _deep_merge,
    _is_uri,
    _read_yaml,
    _ref_is_safe,
    confine_config_path,
)
from .models import (
    _model_for_tier,
    _stage_backend,
    resolve_model,
)
from .stages import (
    _apply_backend_defaults,
    _load_agent_preset,
    expand_stages,
)
from .lanes import (
    CODE_REVIEW_TEMPLATE,
    CORE_TEMPLATES,
    IMPLEMENTOR_TEMPLATE,
    LANES,
    RESOLVE_THREADS_TEMPLATE,
    SECURITY_REVIEW_TEMPLATE,
    Lane,
    _PR_REVIEW_EVENTS,
    _codex_stages,
    _ensure_supported_review_graph,
    _has_codex_code_review,
    _has_codex_push_review,
    _has_codex_security_review,
    _has_implement_stage,
    _needs_codex_pat,
    _pr_review_triggers,
    _runs_on_pr_review,
    _wants_push_review,
    select_templates,
)
from .context import (
    _TOKEN,
    _build_steps,
    _resolve_implementer_model,
    build_context,
    render_template,
)
from .config import (
    _validate_semantics,
    load_config,
    resolve_extends,
    validate_config,
)
from .pipeline import (
    main,
    render_all,
)
