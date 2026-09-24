"""Data constants for the pipeline renderer: package paths, provider/backend ids, gate
strengths, preset build commands, and profile stage graphs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Toolkit data (schema + templates) ships INSIDE this package, so it is found the same
# way in a source checkout and in an installed wheel — no repo layout is assumed.
PKG_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PKG_ROOT / "config.schema.json"
TEMPLATE_ROOT = PKG_ROOT / "templates" / "workflows"
AGENTS_DIR = PKG_ROOT / "templates" / "agents"

# Default NAME of the real-user PAT the review lane pushes/posts with when `platform.auth.token_secret`
# is not set. Provider-neutral (the toolkit is provider-agnostic); the value lives in CI secrets.
DEFAULT_TOKEN_SECRET = "REMEDIATION_TOKEN"

GITHUB_ROLE_MAP = {
    "owner": "OWNER",
    "member": "MEMBER",
    "collaborator": "COLLABORATOR",
    "contributor": "CONTRIBUTOR",
}

# Provider ids. Provider is the primary knob: a stage declares which vendor runs it, and the
# toolkit renders OpenAI via Codex and Anthropic via Claude Code today. The executor/tool below is
# derived from the provider unless a stage pins `backend` explicitly.
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
# The Anthropic provider id was previously `claude`; rejected with a migration error (see
# _validate_semantics) so an upgraded config fails loud instead of resolving the wrong key secret.
RENAMED_ANTHROPIC_PROVIDER = "claude"

# Backend (executor/tool) names, referenced in routing/model logic across modules — kept as named
# constants so the strings are not repeated as literals in comparisons.
BACKEND_GENERIC = "generic"                     # the provider-agnostic runner (roadmap adapter)
BACKEND_CLAUDE_ACTION = "claude-code-action"    # Anthropic's Claude Code
BACKEND_CODEX = "codex"                         # OpenAI's Codex

# The coding tool the toolkit renders for each provider when a stage does not pin `backend`.
PROVIDER_TOOL = {
    PROVIDER_ANTHROPIC: BACKEND_CLAUDE_ACTION,
    PROVIDER_OPENAI: BACKEND_CODEX,
}

# Backends that consume a resolved model from the contract. App backends (codex, openhands,
# swe-agent, pr-agent) choose their own model, so resolution is skipped.
BACKENDS_NEEDING_MODEL = {BACKEND_GENERIC, BACKEND_CLAUDE_ACTION}

# Gate strengths a stage can carry.
GATE_ADVISORY = "advisory"
GATE_BLOCKING = "blocking"

# Stage types whose Codex stage drives the on-push review lane (request-review + resolve-threads).
REVIEW_LANE_TYPES = {"review", "security"}

# Preset -> default build commands (pre-fill; explicit build.commands override per key).
# Mirrors docs/CONFIGURATION.md "Presets".
PRESET_COMMANDS: dict[str, dict[str, str]] = {
    "python": {"install": "pip install -r requirements.txt", "lint": "ruff check .", "test": "python -m pytest"},
    "maven": {"install": "mvn -q -N install", "lint": "mvn -q spotless:check", "test": "mvn -q verify"},
    "gradle": {"install": "./gradlew dependencies", "lint": "./gradlew check -x test", "test": "./gradlew test"},
    "node": {"install": "npm ci", "lint": "npm run lint", "test": "npm test"},
    "go": {"install": "go mod download", "lint": "golangci-lint run", "test": "go test ./..."},
    "rust": {"install": "cargo fetch", "lint": "cargo clippy -- -D warnings", "test": "cargo test"},
    "dotnet": {"install": "dotnet restore", "lint": "dotnet format --verify-no-changes", "test": "dotnet test"},
    "custom": {},
}

# Profile stages carry a provider so a profile renders correctly out of the box: implement/plan/docs
# run Claude Code (anthropic), review/security/test run Codex (openai). Without it, an unprovidered
# review stage would inherit `defaults.provider` and silently render no Codex lane.
PROFILE_STAGES: dict[str, list[dict[str, Any]]] = {
    "minimal": [
        {"id": "implement", "type": "implement", "provider": PROVIDER_ANTHROPIC, "gate": GATE_ADVISORY},
        {"id": "review", "type": "review", "provider": PROVIDER_OPENAI, "gate": GATE_ADVISORY},
    ],
    "standard": [
        {"id": "implement", "type": "implement", "provider": PROVIDER_ANTHROPIC},
        {"id": "review", "type": "review", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "security", "type": "security", "provider": PROVIDER_OPENAI, "gate": GATE_ADVISORY},
    ],
    "full": [
        {"id": "plan", "type": "plan", "provider": PROVIDER_ANTHROPIC, "gate": GATE_ADVISORY},
        {"id": "implement", "type": "implement", "provider": PROVIDER_ANTHROPIC},
        {"id": "security", "type": "security", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "test", "type": "test", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "integration-test", "type": "integration-test", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "review", "type": "review", "provider": PROVIDER_OPENAI, "gate": GATE_BLOCKING},
        {"id": "docs", "type": "docs", "provider": PROVIDER_ANTHROPIC, "gate": GATE_ADVISORY},
    ],
    "custom": [],
}

# Agent contract files change the behavior/security posture of later automation, so they must never
# ride the review fast path, whatever routing.fast_path.exclude is set to (root and nested).
MANDATORY_FAST_PATH_EXCLUDE = ["AGENTS.md", "CLAUDE.md", "**/AGENTS.md", "**/CLAUDE.md"]
