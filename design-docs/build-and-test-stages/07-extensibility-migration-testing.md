# 07 — Extensibility, Migration and Testing

## Extension points (and what each costs)

| You want to add | You change | Core change? |
|---|---|---|
| A new tool as a check (linter, scanner, load test, SQL validation) | Config only: a `custom` stage with `run.commands`, or an observed stage | No |
| A new language / toolchain preset | A preset entry (data) for `build.preset` | No |
| A CI or service Stagr does not run | An observed stage naming its result and producer | No |
| A new CI/CD platform | A renderer package plus its capability descriptor (05) | No |
| A new way to read a result (new evidence source) | A new evidence kind and its reader in the platform package | Small: one enum value, one vector group |
| A new stage kind | Avoid. Kinds only change defaults (Decision D1) | Yes (deliberately hard) |

The bias is on purpose: everything teams do every week is config; everything that needs code is
rare and lives at the edge.

## Testing strategy

Fast to slow, matching `AGENTS.md`:

| Layer | What it proves | Runs in CI as |
|---|---|---|
| 1. Schema and config | New keys, exclusions (`run` vs `observe`), bad names rejected, secret values never echoed | `validate_config.py`, `test_cli.py` |
| 2. Pure mapping tests | Native outcome to `(state, conclusion)`; latest-attempt rule; dependency table | `test_neutral_core_models.py` |
| 3. Shared conformance vectors | The same input/output cases for the neutral reference *and* every platform runtime | both of the above |
| 4. Render structure tests | Security rules S1 to S10 hold in the rendered artifact (no secret in execute, no checkout in publish, read-only token, pinned, timeout) | `test_render.py` |
| 5. Behavioural tests with a strict fake platform CLI | End-to-end publish, reconcile, sweep, wake-up, re-run behaviour on the real runtime | existing stage-signal test package |
| 6. Governance interop | A published check-stage result is accepted or rejected by the real merge gate script | existing interop test |
| 7. Static workflow lint | Rendered pipeline files pass the platform's own linter (for GitHub: actionlint) | existing render tests |
| 8. Mutation checks | Deliberately break the mapping and security assertions; tests must fail | run by the implementer per PR, results in the PR |
| 9. Dogfood smoke | The repository runs its own build and unit test through Stagr on a real pull request | Phase 7 acceptance |

Tests use behaviour assertions (not substring greps of rendered text) wherever a behaviour
exists to assert. Each test module stays within the 350-line limit (`AGENTS.md`).

## Conformance vectors

A vector is a small JSON case: `id`, `description`, `input` (observations), `expected`
(`state`, `conclusion`, `reason`). The neutral reference and each platform runtime load the same
files. A platform adds its own **adapter fixtures** (platform payload to neutral observation)
and must pass the neutral vectors unchanged.

| Group | Cases (examples) |
|---|---|
| V-N native outcome | success passes; failure, timeout, cancelled fail; skipped, neutral and missing do **not** pass |
| V-H head binding | result for an older head is ignored; head moved during a run is refused |
| V-A attempts | latest attempt wins both ways (green after red, red after green) |
| V-O observed | right producer passes; wrong producer ignored; same name from a second producer is ambiguous and not passed; no result stays pending; timeout becomes `FAILED` |
| V-D dependencies | wait on missing / running / red / blocked upstream; `FAILED` upstream propagates |
| V-G gate | one red blocking stage blocks; advisory red does not; open review thread blocks; all green merges |
| V-S security | hostile command, branch and title strings stay inert; secret-named fields never echoed |

The vector set is versioned. A renderer states which vector version it passes; a new version
adds cases and never changes an old expected value.

## Versioning and compatibility

- Config: new keys are optional (P9). Schema `version` stays `1`.
- `StageResultSignal`: schema version 1 unchanged.
- Capability descriptor: has its own version number; a renderer built for version N keeps
  working until N is retired with notice.
- Vectors: versioned as above.

## Migration

| From | To | How |
|---|---|---|
| A `build` / `test` stage that rendered a placeholder | A real managed stage | Set `build.commands`. Today such a stage renders stub steps that run nothing and has no evidence source (only the two review backends do). Phase 1 first pins with a test exactly what it publishes today. **Behaviour change to call out in release notes:** a *blocking* check stage with no commands and no `observe` fails closed, and `plan`/`doctor` report it before `apply` |
| Legacy schema `type` values (`integration-test`, `plan`, `docs`, `release`) | Neutral kinds | Accepted with a documented mapping and a deprecation warning; alignment happens once in Phase 1 |
| `modules.sonar: true` | An observed `sonar` stage | Deprecated alias for one release; `doctor` prints the equivalent stage; both together is an error (06) |
| A repository's own CI (Jenkins, GitLab CI, Azure Pipelines, ...) | Observed stage | Name its result and producer; nothing else changes |
| This repository's `Validate` workflow | Managed `build` + `unit-test` stages | Phase 7: run both side by side on several pull requests, compare, then swap the required checks. Changing branch protection is a repository-admin action, done by a human |

Note on this repository's migration: GitHub Actions results are all authored by the same
GitHub-owned app, and a pull request can edit its own workflow files. Observing the existing
`Validate` result would therefore give a weak guarantee (04, T3). The managed path, whose
definition comes from the trusted base, is the recommended one.

**Rollback:** every new stage can be switched off with `enabled: false`, and every phase is
additive, so reverting is a config or single-PR revert.

## Documentation to ship

- `docs/CONFIGURATION.md`: the new stage keys, with the two examples from 03.
- `docs/ARCHITECTURE.md`: the two planes and the three units.
- A short "Platform authors" page: capability descriptor, vectors, adding a platform (05).
- `docs/CLI.md`: new `plan`/`doctor` messages (drift, capability errors, deprecations).
- Keep the set minimal: extend existing pages, add one new page only for platform authors.
