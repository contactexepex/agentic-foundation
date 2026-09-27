# Stagr Neutral Core — Provider, Backend, and Model

**Status:** Design phase — not yet implemented

---

## Overview

Three separate concepts govern how a stage is executed by an external service. Keeping
them separate is critical for the provider-neutral goal: the same API provider can offer
multiple backends, and the same backend can run on multiple models.

---

## The three concepts

### Provider

The **provider** identifies the API/credential layer — who issues the API key and hosts
the service.

Examples: `openai`, `anthropic`, `deepseek`, `google`

The provider determines:
- Which secret alias is used to look up credentials (see Secret resolution below)
- Which BackendRenderers are available for use with this provider

### Backend

The **backend** identifies the **invocation mechanism** — how the stage is actually
triggered. Two stages can share the same provider but use completely different backends.

Examples:

| Provider | Backend | What it does |
|---|---|---|
| `openai` | `codex` | Posts `@codex review` or `@codex security review` as a PR comment |
| `openai` | `generic` | Calls the OpenAI Chat Completions API directly |
| `anthropic` | `claude-code` | Invokes Claude Code in a CI workflow step |
| `anthropic` | `generic` | Calls the Anthropic Messages API directly |
| `deepseek` | `generic` | Calls the DeepSeek API directly |

### Model

The **model** is the specific model identifier to use within the backend. It is optional
— when omitted, the backend uses its own default model.

Examples: `gpt-4o`, `claude-opus-5-5`, `deepseek-coder`

---

## Default resolution

When `backend` or `model` is omitted from the config, Stagr applies defaults at
normalization time (after profile expansion, before rendering):

```
provider: openai  → default backend: codex
provider: openai, backend: codex  → default model: (backend-defined)
provider: anthropic  → default backend: claude-code
provider: deepseek  → default backend: generic
```

Defaults are registered per provider by the BackendRenderer registry. No defaults are
hardcoded in the neutral contract itself — they are part of the backend registration.

After default resolution, every `NormalizedStage` always has non-null `provider`,
`backend`, and either an explicit `model` or a documented backend default (null in the
normalized model = "use backend default").

---

## NormalizedStage fields (provider/backend/model)

```
NormalizedStage {
  ...
  provider: string          // always present after normalization
  backend:  string          // always present after normalization
  model:    string | null   // null = backend's own default; never "unknown"
  ...
}
```

---

## Secret resolution

Secret values are **never** part of the config. The config contract explicitly excludes
them. Instead, Stagr resolves secrets at render time using **secret aliases**:

### SecretRef

A `SecretRef` is a neutral reference to a secret that a stage execution artifact needs
at run time. It has two fields:

```
SecretRef {
  alias:     string   // neutral name used in the ExecutionPlan (e.g. "PROVIDER_API_KEY")
  envName:   string   // the actual environment/repository secret name on the platform
                      // (e.g. "OPENAI_API_KEY", "REMEDIATION_TOKEN")
}
```

`ExecutionPlan.requiredSecrets` contains `SecretRef[]`. The PlatformRenderer maps each
`alias` to the platform's secret reference syntax (e.g., GitHub's
`${{ secrets.OPENAI_API_KEY }}`).

### How aliases are resolved

1. The BackendRenderer declares which `alias` names a stage requires (e.g.,
   `PROVIDER_API_KEY`, `TRUSTED_COMMENTER_TOKEN`).
2. The operator configures the mapping from alias to actual platform secret name in
   provider configuration (outside the stage declaration, in a provider config block —
   or via convention: alias = platform secret name when no override is given).
3. The PlatformRenderer renders the actual secret reference into the generated artifact.

### Why this matters

The current implementation hardcodes `REMEDIATION_TOKEN` as the secret name in the
workflow scripts. This leaks a platform-specific secret name into the neutral design.
Under the correct model, `REMEDIATION_TOKEN` is the platform secret name for the alias
`TRUSTED_COMMENTER_TOKEN` — that mapping is provider configuration, not part of the
neutral stage declaration.

---

## Provider configuration block (V1 sketch)

```yaml
# .agentic/config.yml
providers:
  openai:
    secrets:
      PROVIDER_API_KEY: OPENAI_API_KEY           # alias → platform secret name
      TRUSTED_COMMENTER_TOKEN: REMEDIATION_TOKEN  # alias → platform secret name
```

This block is optional in V1 when convention-based resolution is sufficient (alias ==
platform secret name). It becomes required when the platform secret names differ from
the aliases the backend declares.

> **V1 decision:** Provider configuration lives in `config.yml` under the `providers:`
> block. A separate `.agentic/providers.yml` is not needed in V1. Keeping everything in
> one file simplifies the operator experience and the Stagr CLI's config loading path.

---

## Validation

Static validation (see `07-validation.md`) must verify:

- A registered BackendRenderer exists for every `(provider, backend)` pair in the config
- If `model` is specified, the BackendRenderer accepts that model value (or validation
  is deferred to doctor/apply when the backend requires a live API call to validate)
- All aliases declared by the BackendRenderer for a stage are present in provider
  configuration or can be resolved by convention
