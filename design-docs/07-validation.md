# Stagr Neutral Core — Validation Checklist

**Status:** Static checks V-S01 to V-S09, V-S11 and V-S14 are implemented and run in `stagr plan` and
`stagr apply`; today V-S01 still accepts unknown top-level keys. V-S15 (check stages), V-S16 (engine
file), V-S17 (platform axes) and the environment checks (`stagr doctor`) are not implemented yet.

---

## Overview

Validation separates into two phases: **static** (config alone, no environment access)
and **environment** (requires network access, credentials, and a configured platform).

---

## CLI commands

| Command | What it checks | Requires environment |
|---|---|---|
| `stagr plan` | Static validation + lists planned artifacts (what would be written) | No |
| `stagr doctor` | Static validation + environment readiness | Yes |
| `stagr apply` | Static validation, then renders and writes artifacts | No (but `doctor` should pass first) |

`stagr plan` and `stagr apply` share the same static validation pass. Any static error
that fails `plan` also fails `apply`, except V-S16 (engine file), which `apply` skips because it
writes that file.

---

## Static validation

Errors here fail `stagr plan` and prevent `stagr apply` from writing any artifacts (V-S16 is the
exception described under that check).

`validate_config` in `stagr/core/config_validation.py` is the front door for V-S01 to V-S06:
schema, publisher block, profile, dependency references, cycles, and skill files.
`stagr/cli/render_pipeline.py` (`load_render_inputs`) runs it, then V-S07 to V-S09 and V-S11;
`stagr plan` and `stagr apply` both call that one function. `stagr doctor` (issue #203) is planned
and will call it too. The repository's own CI
check is `python .github/scripts/validate_config.py`.

### V-S01 — Config schema validity

All required fields are present; all field values are recognized enum members or valid
strings; and no key is unknown, at any level. The rule and the list of recognized keys are in
`01-neutral-config-contract.md`, "The schema is the key list".

### V-S02 — Schema version support

The declared `version` is supported by this Stagr CLI. An unsupported version is a hard
error; the CLI must not attempt to render it.

### V-S03 — Stage ID uniqueness

No two stages share the same `id`.

### V-S04 — Dependency graph acyclicity

No cycles exist in the `dependencies` graph. Detection: topological sort; any cycle
causes a static error naming the cycle.

### V-S05 — Dependency reference validity

Every id referenced in any stage's `dependencies` array exists as a stage id in the
config.

### V-S06 — Skill file existence

Each agent stage's `skill` resolves to an existing file: the repository's own
`.agentic/skills/<id>/SKILL.md` when present (an override), otherwise the shipped
`stagr/templates/skills/<id>/SKILL.md`.
Stages with a `commands` or `observed` executor have no skill.

### V-S07 — BackendRenderer availability

A registered BackendRenderer exists for every `(provider, backend)` pair of the agent stages
in the config.

### V-S08 — Platform renderer compatibility

The target PlatformRenderer supports every `InvocationKind` present in the
ExecutionPlans that would be generated. Catches `CI_STEP` incompatibilities with
the target platform.

### V-S09 — Route dependency-closure

When `routing.fast_path.enabled: true`, the stage set declared for each route
(`stages.fast` and `stages.normal`) must be dependency-closed: for every stage S in the
set, all of S's transitive dependencies are also in the set.

### V-S11 — Routing policy consistency

Implemented in `find_dormant_routing_warnings`; `plan` and `apply` print the warning on stderr.

When `routing.fast_path.enabled: false`, the presence of `globs` or `stages` keys
is **allowed but produces a warning** ("dormant route configuration — fast_path is
disabled; routing keys are present but will not be evaluated"). This is not a static
error. Operators may intentionally keep a routing config dormant (e.g., preparing for
future activation without enabling it yet), and treating it as an error would force
unnecessary edits when toggling `enabled`.

### V-S12 — Secret alias resolution

Holds by construction, so it has no separate check: the Phase 1 resolver falls back to "the alias
is the secret name" when no mapping exists (`stagr/core/render_loop.py`), so an alias is never
unresolvable.

All `SecretRef.alias` values declared by the BackendRenderer for each stage are
resolvable: either an explicit mapping exists in provider configuration, or the alias
equals the platform secret name by convention. Static resolution means the alias is
registered; run-time presence is checked by `stagr doctor`.

### V-S14 — Trusted-role value validation

Every string in `platform.trusted_roles` must be a recognised :class:`AuthorRole`
value (``owner``, ``member``, ``collaborator``, ``contributor``). An unrecognised
string is a hard static error.

### V-S15 — Check-stage rules

For stages with a `commands` or `observed` executor (`09-check-stages.md`, section 2):

1. A stage declares `commands` or `observe`, never both; `commands` appears only on `custom`
   stages.
2. Every `commands` stage has at least one command, after the `build:` block is applied to the
   `build` stage. A stage with nothing to run is an error.
3. `observe.check` and `observe.producer` are both present; an observed stage has no
   `depends_on`. The target platform renderer accepts the form of `observe.producer`
   (`09-check-stages.md`, section 2, rule 3).
4. `timeout_minutes` is an integer from 1 to 360.
5. `BUILD` stages are never agent stages; `REVIEW` and `SECURITY` stages are always
   `agent` stages with a blocking gate.
6. No key named `secrets` exists on a stage. Unknown keys are rejected as in V-S01.

### V-S16 — Engine file present and unchanged

The rules engine file that `stagr apply` writes (`06-runtime-boundary.md`, "The engine file") is
present and identical to the file this Stagr version would write. A missing, edited or
out-of-date engine file fails `stagr plan`. V-S16 is the one static check that `stagr apply`
skips, because `apply` is what writes the engine file: on a fresh repository and after an upgrade
it writes the current file.

### V-S17 — Platform axes known

`platform.scm` is present, and `platform.scm` and `platform.ci` (when set) each name a platform
with a renderer. The platform block is described in `01-neutral-config-contract.md`, "The
platform block".

---

## Environment validation (`stagr doctor`)

> **Proposed redesign:** [doctor/](doctor/README.md) redefines this section (two modes, CI-only live
> checks, V-E02 as the publisher App). It is under review; until accepted, the text below stands.

Warnings and errors here do not prevent `stagr apply` from running, but they indicate
conditions that will cause run-time failures. All `doctor` checks should pass before
relying on the generated pipeline.

### V-E01 — Required secrets present

Every `SecretRef.envName` in every `ExecutionPlan.requiredSecrets` is configured as a
repository or environment secret on the target platform. Missing secrets produce
`doctor` errors.

### V-E02 — Backend app/integration installed

Each provider's platform app or integration is installed on the repository and has the
permissions that the backend requires (for example, writing comments on the change and reading
review threads).

### V-E03 — Platform permissions

The repository grants the workflow permissions that the generated artifacts require. Validates
against the minimal permission blocks that the PlatformRenderer will generate.

### V-E04 — TrustPolicy author roles reachable

The `trustedRoles` configured in `TrustPolicy` includes at least one role that the
repository's expected change authors hold. A TrustPolicy that excludes all likely authors
will cause every change to be skipped.

---

## Notes

**V-S10 is obsolete.** It guarded an automatic-merge setting that the schema does not have. There is
no check with that number.

**V-S12 has no separate check.** The resolver's convention fallback means every alias resolves;
see V-S12 above.

**V-S13 (NON_BLOCKING dependency warning) has been removed.** `NON_BLOCKING` controls
gate participation, not what conclusion a stage can produce. A `NON_BLOCKING`
stage can produce `conclusion = PASS` and is a perfectly valid dependency for any stage,
including `BLOCKING` ones. The original rule was based on a false premise.

**V-E04 from the previous draft (Codex concurrency constraint) has been removed.**
The claim that the Codex backend errors on concurrent code + security reviews has not
been empirically verified. Until the behavior is confirmed through testing, no
architecture or validation rule based on this assumption should be included.

**Operators are responsible for conformance to reference contracts.** Validation
confirms that the *shipped config* conforms to the Stagr contract. It does not
pre-emptively guard against future operator edits that would break conformance —
that is the same model used by Kubernetes manifests, GitHub Actions workflows, and
every widely-adopted configuration-driven tool.
