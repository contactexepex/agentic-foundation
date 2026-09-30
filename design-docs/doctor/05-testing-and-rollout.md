# Doctor — Testing and Rollout

Part of the [doctor design set](README.md). Follows the backlog standard in `AGENTS.md`: explicit
acceptance criteria, each with a test.

## Acceptance criteria

| # | Criterion | Test |
|---|---|---|
| A1 | Doctor runs static validation first and stops before environment checks on a static error | Unit: invalid config exits non-zero, prints no `V-E` line |
| A2 | Local mode makes no network call and reads no credential; live checks show `SKIP` | Unit: network client absent; run against the dogfood config, exit 0 |
| A3 | Local mode prints the provisioning checklist and CI snippet, derived from the same render as `apply` | Unit: checklist names match `required_secrets` and the declared permissions |
| A4 | V-E01 names each missing secret and its stage | Unit (presence flags): one missing secret; assert secret and stage in output |
| A5 | V-E02 names the App ID when not installed | Unit (fake GitHub client): `404`; assert App ID in output |
| A6 | V-E02 names the missing private-key secret, and c/d become `SKIP` | Unit: key flag `false`; assert name, and c/d blocked |
| A7 | V-E02 lists each missing or too-weak permission | Unit: installed permissions lack `checks: write`; assert it is listed |
| A8 | Missing required `--ci` input is an ERROR, never a silent SKIP | Unit: unset flag in `--ci` |
| A9 | V-E04 warns on `owner`-only roles | Unit |
| A10 | Exit code is 0 with no ERROR, else 1; secret values never appear in output | Unit: sentinel secret value absent from stdout/stderr |
| A11 | Declared artifact permissions match the docs table | Test compares the renderer's union to `docs/CONFIGURATION.md` |
| A12 | Optional probes: with `STAGR_PLATFORM_TOKEN`, V-E03 and V-E04 report ERROR/WARN from a fake client; without it, both `SKIP` and exit code is unaffected | Unit (fake client, with and without token) |

## Test approach

- Fast, deterministic unit tests only. A fake GitHub client and fake environment are injected; tests
  never touch the real network (C3, C8).
- Follow the existing layout: new tests under `.github/scripts/` in a focused sub-package if a module
  passes 350 lines; run by the existing `validate.yml` commands.
- Existing gates stay: `python .github/scripts/validate_config.py`, `test_neutral_core_models.py`,
  `test_cli.py`, `py_compile` on changed files.
- **One real run.** After merge, run `stagr doctor --ci` in this repository (App 5125793, secret
  `STAGR_APP_PRIVATE_KEY`) to confirm F1 to F4. Expect PASS. Then run once on a scratch branch with a wrong
  App ID to confirm the ERROR text.

## Verify GitHub facts first

Before code, confirm F1 to F7 ([01](01-constraints.md)). If F3 fails, V-E02 c/d need a different App
signal and the owner decides again. If F1 fails, V-E01 needs a different presence signal.

## Docs to update with the implementation

- `design-docs/07-validation.md`: replace the V-E section with a pointer to [03](03-validation-design.md)
  (in particular V-E02, which today means "provider integration" and is redefined here).
- `design-docs/00-overview.md`: doc-set table.
- `docs/CLI.md`: doctor section, setup runbook by role, network rule.
- `docs/CONFIGURATION.md`: point the App permissions table at the declared set.
- `docs/stagr/roadmap.md`: update the `doctor` probes line.
- `stagr/cli/__init__.py` docstring and CLI help tests.

## Rollout

1. **This PR:** the design set only. Review by Codex and the owner. The owner has decided D3, D6, D7
   and D8.
2. **One implementation PR** for #203: core check types and requirements, GitHub probes, `doctor`
   command, tests, docs. One PR because the checklist, the checks, and the declared permissions must
   agree; splitting them invites drift (the same reason `plan` and `apply` shipped together).
3. **Post-merge:** the one real `--ci` run, then close #203.
