# 03 — Config Contract

This document defines what an operator writes in `.agentic/config.yml`. The rule from Charter
section 6 applies: **the common repository needs about ten lines**, and everything else is
optional.

## The common case: nothing new to learn

The existing top-level `build:` block already says what "green" means for a repository. It stays
the single source of truth for the baseline build and test stages:

```yaml
version: 1
platform: { type: github }

build:
  preset: maven          # python | maven | gradle | node | go | rust | dotnet | custom
  # commands:            # optional overrides; a preset fills sensible defaults
  #   install: mvn -B -q -DskipTests install
  #   lint: mvn -B -q checkstyle:check
  #   typecheck: ""      # not needed for this language
  #   test: mvn -B verify
```

With that block, `stagr init` generates the two baseline check stages (`build` and `unit-test`)
next to the two review stages. No `stages:` entry is needed. This is what P7 ("reference, do
not re-declare") means here: the commands are declared once, in `build:`.

How `build:` maps to stages:

| `build.commands.*` | Runs in stage | Notes |
|---|---|---|
| `install`, `build`, `lint`, `typecheck` | `build` | Dependencies, compile / package, static checks, in this order. Any failing step fails the stage |
| `install`, then `test` | `unit-test` | Runs after `build` (dependency). Stages share nothing (06), so it installs dependencies again on its own runner; a `test` command must build whatever it needs (the preset defaults normally do; `custom` has none). Fails the stage if a step fails |

**Schema addition (Decision D12):** `build.commands` has no compile/package key today (its
`install` for some presets, for example Maven, does not compile). This plan adds an optional
`build.commands.build` and gives every preset a default for it, so "the code compiles" is a real
command rather than a side effect of `install` or `test`.

A command that is empty or missing is skipped. If a stage would have no commands at all, see
"A blocking check stage with nothing to run" below.

## Adding more check stages

Extra check stages use the ordinary `stages:` list with a few optional additions.

```yaml
stages:
  - id: integration-test
    type: custom              # any check that is not build / unit test
    gate: advisory            # advisory | blocking (always write it for custom stages)
    depends_on: [build]
    run:
      commands: ["./scripts/integration.sh"]
      timeout_minutes: 30
      secrets: [INTEGRATION_DB_URL]      # names only, never values (P3)

  - id: analysis
    type: custom
    gate: blocking
    execution: observed       # the team's CI or an external service already runs it
    observe:
      check: "Code Analysis"             # the result name the platform shows
      producer: "<producer identity>"    # who is allowed to author it
```

### New optional stage keys (deliberately few)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `execution` | `managed` \| `observed` | `managed` | Who runs the work (see 02) |
| `run.commands` | list of strings | none | Commands for a **custom** stage, in order; stop at the first failure |
| `run.timeout_minutes` | integer 1..360 | 30 | Hard limit; timeout is `COMPLETED` + `FAILED` |
| `run.secrets` | list of names | none | Secret **names** the platform injects. Never values |
| `observe.check` | string | required if observed | Name of the platform result to read |
| `observe.producer` | string | required if observed | Identity allowed to author that result |
| `observe.timeout_minutes` | integer 1..10080 | none (wait) | If the result never appears, the stage becomes state `FAILED` after this time (06) |

There is no `purpose`, `env` or `reports` key. A label is a `name:`; a non-secret environment
value is part of the command (`FOO=bar ./run.sh`); test-report attachment is the CI system's job
(Charter section 6: reference, do not re-declare). Each key above changes behavior.

Rules the schema and static validation enforce:

1. **Single source of truth for commands.** The `build` and `unit-test` stages take their commands
   **only** from `build:`; `run.commands` on them is an error. `run.commands` exists only for other
   (`custom`) managed stages.
2. `run` is allowed only when `execution` is `managed`; `observe` only when `observed`. A stage
   with both, or with `execution: observed` and no `observe.producer`, is a configuration error.
3. `observe.producer` is **mandatory**. Reading a result by name alone would let anyone who can
   create a check of that name satisfy the gate (see 04, threat T4).
4. `run.secrets` names must match `^[A-Z][A-Z0-9_]*$`, must not use a prefix the platform reserves
   (for example `GITHUB_` on GitHub), and **must not name any credential Stagr itself uses**: the
   publisher private-key secret, the platform token secret, or any provider or backend secret
   that the config resolves for another stage. Naming one is a static error (a V-S12-style
   check), because it would hand that credential to the untrusted work unit (04, S1).
5. Values of secret-like fields are rejected at load time and error messages never echo them
   (existing `describe_schema_error` behavior).
6. A managed stage with `secrets` is **not** run for untrusted pull requests, and no managed stage
   runs fork code at all (04).
7. `depends_on` may only name existing stages and must be acyclic (already enforced).
8. Existing keys keep their meaning: `gate`, `enabled`, `triggers`, `depends_on`, `name`.

### What is deliberately missing

No `matrix`, `services`, `cache`, `container`, `if`, `artifacts`, `retries`, `parallelism`, `env`,
`runs_on` or `purpose` keys. These are CI-system features or labels. A team that needs them writes
the job in its own CI and uses `execution: observed`. This keeps the config small and stops Stagr
from becoming a second CI language.

## Gate defaults

| Stage kind | Default `gate` | Rationale |
|---|---|---|
| `build`, `test` | `blocking` | Baseline (01) |
| `review`, `security` | `blocking` | Baseline (01); already the neutral default |
| `custom` | **Required.** Omitting `gate` on a `custom` stage is a configuration error in both lanes, naming the stage (Decision D16) | The two config lanes disagree on an omitted `gate` today (one blocks, one does not). Choosing either would silently change the other lane, and the choice decides whether a failed stage can merge, so the operator states it |

`stagr init` writes the four baseline stages as blocking. Their `build:` commands are commented
placeholders (option A, already implemented for review/security).

## A blocking check stage with nothing to run

One rule, stated once (used by 05, 07 and 08):

- `stagr plan` **warns**; `stagr doctor` reports an **error** naming the stage.
- If applied anyway, the stage runs and publishes `FAILED` with the reason "no commands
  configured". It never passes and never renders a silent no-op.
- To resolve: set `build.commands` (or the preset), mark the stage `execution: observed`, or turn
  it off with `enabled: false`.

## Validation and errors

- Unknown keys are rejected (`additionalProperties: false`, already the case).
- `stagr doctor` and `stagr plan` report each problem with the config path
  (for example `stages/2/observe/producer: required`).
- Values of secret-like fields are never printed (existing redaction).
- **Known mismatch to fix in delivery Phase 1:** the schema's `type` enum does not contain
  `build`, and contains values that the neutral `StageKind` lacks (`plan`, `integration-test`,
  `docs`, `release`). The `build` stage is therefore reachable today only through
  `type: custom`, which maps to `StageKind.CUSTOM`. Phase 1 aligns the enum with `StageKind`
  (adds `build`, keeps the legacy values accepted with a mapping and a deprecation note).

## Versioning

All new keys are optional and additive (P9). A config without them behaves as today. The schema
`version` stays `1`. A future breaking change would bump it, never silently change meaning.

## Configuration budget check

For the common repository: `platform.type`, `build.preset`, and optionally `platform.publisher`
(already required for blocking stages). Everything in "Adding more check stages" is opt-in and
sits next to the rule it configures.
