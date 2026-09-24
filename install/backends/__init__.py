"""Agent backends for agentic-foundation stages.

A backend turns a resolved stage (skill + provider + model) into a concrete
invocation. `generic` is the built-in, provider-agnostic runner; named adapters
(claude-code-action, openhands, pr-agent, codex, swe-agent) wrap OSS agents.
"""
