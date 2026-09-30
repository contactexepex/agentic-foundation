"""Provider ids, backend names, and the default backend of each provider.

A stage names a provider; unless the stage pins ``backend`` explicitly, the backend is the
one listed here. Each backend renderer under ``stagr/core/renderers/`` declares the same
provider and backend strings as its class attributes.
"""
from __future__ import annotations

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"

BACKEND_CLAUDE_CODE_ACTION = "claude-code-action"
BACKEND_CODEX = "codex"

DEFAULT_BACKEND_BY_PROVIDER: dict[str, str] = {
    PROVIDER_ANTHROPIC: BACKEND_CLAUDE_CODE_ACTION,
    PROVIDER_OPENAI: BACKEND_CODEX,
}
