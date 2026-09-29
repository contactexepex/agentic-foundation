# 07 — Extensibility, Migration and Testing

## Extension points (and what each costs)

| You want to add | You change | Core change? |
|---|---|---|
| A new tool as a check (linter, scanner, load test, SQL validation) | Config only: a `custom` stage with `run.commands`, or an observed stage | No |
| A new language / toolchain preset | A preset entry (data) for `build.preset` | No |
| A CI or service Stagr does not run | An observed stage naming its result and producer | No |
| A new CI/CD platform | A renderer package plus its capability declaration (05) | No |
| A new way to read a result (new evidence source) | A new evidence kind and its reader in the platform package | Small: one enum value, one vector group |
| A new stage kind | Avoid. Kinds only change defaults (Decision D1) | Yes (deliberately hard) |

The bias is on purpose: everything teams do every week is config; everything that needs code is
rare and lives at the edge.

## Testing strategy

Fast to slow, matching `AGENTS.md`:

| Layer | What it proves | Runs in CI as |
|---|---|---|
| 1. Schema and config | New keys, exclusions (`run` vs `observe`), bad names rejected, secret values never echoed | `validate_config.py`, `test_cli.py` |
| 2. Pure mapping tests | Native outcome to `(state, conclusion)`; latest-terminal-attempt rule; dependency table | `test_neutral_core_models.py` |
| 3. Shared conformance vectors | The same input/output cases for the neutral reference *and* every platform runtime | both of the above |
| 4. Render structure tests | Security rules S1 to S14 hold in the rendered artifact (no secret or credential in the work unit, no checkout in eligibility or publish, read-only token, pinned, timeout) | `test_render.py` |
| 5. Behavioural tests with a strict fake platform CLI | End-to-end eligibility (including the `RUNNING` lease under concurrent wake-ups, a stale lease and a re-run after `FAILED`; a red re-run after `PASS` that closes the gate and a green one that reopens it; a later wake-up whose eligibility job does not evict a queued publisher; a dead publisher's stale `RUNNING` replaced by the next re-run; an older attempt publishing late; a pending explicit re-run replaced by a wake-up's eligibility job starts no work, logs the skip and leaves the gate closed; a re-run of only the failed jobs), publish, reconcile, sweep, wake-up, re-run behaviour on the real runtime | existing stage-signal test package |
| 6. Governance interop | A published check-stage result is accepted or rejected by the merge gate scripts: the generated `governance.yml` (existing interop test) **and** this repository's foundation gate once it consumes Stagr results (08, I10) | existing interop test; new test in I10 |
| 7. Static workflow lint | Rendered pipeline files pass the platform's own workflow linter (GitHub: `actionlint`) | existing render tests |
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
| V-A attempts | the latest terminal attempt of one lineage decides: green after red passes, and red after a published green turns the result into `COMPLETED` + `FAILED`; an older attempt that publishes late is a no-op (older green after newer red stays red); a second same-name result without shared lineage (or from another producer) stays ambiguous and not passed |
| V-O observed | right producer passes; wrong producer ignored; same name from a second producer is ambiguous and not passed; no result stays pending; timeout becomes `FAILED` |
| V-D dependencies | wait on every non-`PASS` upstream: missing, running, red, blocked, and state `FAILED`; a wake-up never starts a stage that already has a result for the head |
| V-G gate | one red blocking stage blocks; advisory red does not; open review thread blocks; all green merges; a blocking stage turned red or `RUNNING` by a re-run blocks even though its dependents keep their results |
| V-S security | hostile command, branch and title strings stay inert; secret-named fields never echoed |

The vector set is versioned. A renderer states which vector version it passes; a new version
adds cases and never changes an old expected value.

## Versioning and compatibility

- Config: new keys are optional (P9). Schema `version` stays `1`.
- `StageResultSignal`: schema version 1 unchanged.
- Capability declaration: not versioned in V1; it changes together with the code in one pull request.
- Vectors: versioned as above.

## Migration

| From | To | How |
|---|---|---|
| The legacy `Validate` job (`python -m stagr.render`, runs `build.commands` verbatim in one job, may use `${{ secrets.X }}`, publishes no Stagr result) | Managed `build` + `unit-test` stages | Both lanes coexist until I10. The legacy job's freedom to use secrets in `build.commands` does **not** carry over: secrets move to `run.secrets` on a stage that may hold them (04, S5) |
| A `build` / `test` stage that rendered a placeholder | A real managed stage | Set `build.commands`. Today such a stage renders stub steps that run nothing and has no evidence source (only the two review backends do). Phase 1 first pins with a test exactly what it publishes today. **Behaviour change to call out in release notes:** a *blocking* check stage with no commands and no `observe` fails closed, and `plan`/`doctor` report it before `apply` |
| Legacy schema `type` values (`integration-test`, `plan`, `docs`, `release`) | Neutral kinds | Accepted with a documented mapping and a deprecation warning; alignment happens once in Phase 1 |
| `modules.sonar: true` | An observed `sonar` stage | Deprecated alias for one release; `doctor` prints the equivalent stage; both together is an error (06) |
| A repository's own CI (Jenkins, GitLab CI, Azure Pipelines, ...) | Observed stage | Name its result and producer; nothing else changes |
| This repository's `Validate` workflow and foundation gate | Managed `build` + `unit-test` stages | Phase 7: run both side by side on several pull requests and record every difference; then the foundation gate (which today requires the `Validate` check from the trusted workflow, not Stagr stage results) is changed in its own security-reviewed pull request to require the Stagr stage results; then the required checks are swapped. Changing branch protection is a repository-admin action, done by a human |

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
