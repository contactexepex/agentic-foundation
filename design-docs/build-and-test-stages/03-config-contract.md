# 03 — Config Contract

This document defines what an operator writes in `.agentic/config.yml`. The rule from Charter
section 6 applies: **the common repository needs about ten lines**, and everything else is
optional.

## The common case: nothing new to learn

The existing top-level `build:` block already says what "green" means for a repository. It stays
the single source of truth for the baseline build and test stages:

```yaml
version: 1
platform: { kind: github }

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
| `install`, `lint`, `typecheck` | `build` | Compile / package / static checks. Fails the stage if any step fails |
| `test` | `unit-test` | Runs after `build` (dependency). Fails the stage if it fails |

A command that is empty or missing is skipped, not treated as a pass-through of a placeholder.
If a stage would have **no** commands at all, `stagr plan` warns and the stage is rendered as
a visible placeholder that does **not** pass (fail closed, P5) — the operator must either set the
command, disable the stage, or mark it `observed`.

## Adding more check stages

Extra check stages use the ordinary `stages:` list with three optional additions.

```yaml
stages:
  - id: integration-test
    type: custom              # any check that is not build / unit test
    purpose: integration      # optional label, shown in reports, no behavior
    gate: advisory            # advisory | blocking; default is blocking for build/test
    depends_on: [build]
    run:
      commands: ["./scripts/integration.sh"]
      timeout_minutes: 30
      secrets: [INTEGRATION_DB_URL]      # names only, never values (P3)

  - id: sonar
    type: custom
    purpose: sast
    gate: blocking
    execution: observed       # the team's CI or service already runs it
    observe:
      check: "SonarCloud Code Analysis"  # the name the platform shows
      producer: sonarqubecloud           # who is allowed to author it
```

### New optional stage keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `execution` | `managed` \| `observed` | `managed` | Who runs the work (see 02) |
| `purpose` | string | none | Free-text label for reports; never changes behavior |
| `run.commands` | list of strings | from `build:` | Commands to run, in order; stop at the first failure |
| `run.timeout_minutes` | integer 1..360 | 30 | Hard limit; timeout is `COMPLETED` + `FAILED` |
| `run.env` | map name to string | none | Non-secret environment values |
| `run.secrets` | list of names | none | Secret **names** the platform injects. Never values |
| `run.reports` | list of paths | none | Files whose *presence* is informational only (see below) |
| `observe.check` | string | required if observed | Name of the platform result to read |
| `observe.producer` | string | required if observed | Identity allowed to author that result |
| `observe.timeout_minutes` | integer 1..10080 | none (wait) | If the result never appears, the stage becomes state `FAILED` after this time (06) |

Rules the schema enforces:

1. `run` is allowed only when `execution` is `managed`; `observe` only when `observed`. A stage
   with both, or with `execution: observed` and no `observe.producer`, is a configuration error.
2. `observe.producer` is **mandatory**. Reading a result by name alone would let anyone who can
   create a check of that name satisfy the gate (see 04, threat T4).
3. `secrets` accepts names that match `^[A-Z][A-Z0-9_]*$`. Values are rejected at load time and
   error messages never echo them (existing `describe_schema_error` behavior).
4. A managed stage with `secrets` is **not** run for untrusted pull requests (fork policy, 04).
5. `depends_on` may only name existing stages and must be acyclic (already enforced).
6. Existing keys keep their meaning: `gate`, `enabled`, `triggers`, `depends_on`, `name`.

`run.reports` never decides the result. The result is always the platform's native outcome for the
job (02). Reports let a platform attach test results to its own UI where it supports that; a
platform that has no such feature ignores the key.

### What is deliberately missing

No `matrix`, `services`, `cache`, `container`, `if`, `artifacts`, `retries` or `parallelism`
keys. These are CI-system features (goals, non-goals in 01). A team that needs them writes the
job in its own CI and uses `execution: observed`. This keeps the config small and stops Stagr
from becoming a second CI language.

## Gate defaults

| Stage kind | Default `gate` | Rationale |
|---|---|---|
| `build`, `test` | `blocking` | Baseline (01) |
| `review`, `security` | `blocking` | Baseline (01); already the neutral default |
| `custom` | `advisory` | Optional checks never block unless the team says so |

`stagr init` writes the four baseline stages as blocking, with the `build:` commands as
commented placeholders (option A, already implemented for review/security).

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

For the common repository: `platform.kind`, `build.preset`, and optionally `platform.publisher`
(already required for blocking stages). Everything in "Adding more check stages" is opt-in and
sits next to the rule it configures.
