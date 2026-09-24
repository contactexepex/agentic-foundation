#!/usr/bin/env python3
"""Deterministic validation for the agentic-foundation contract.

This is the repository's "green" check (the equivalent of a unit-test suite for a
contract/docs repo). It runs in CI (`validate.yml`) and in the Codex implementor's
validation step. It has no network access and only reads repository files.

Checks:
  1. install/config.schema.json is valid JSON Schema (2020-12).
  2. templates/config/agentic.config.yml.tmpl validates against the schema.
  3. A representative minimal config validates.
  4. Every agent preset (templates/agents/*.yml) references an existing skill dir
     and has a `type`.
  5. Every skill (templates/skills/*/SKILL.md) has YAML frontmatter and a
     structured `verdict` output contract.

Exit code 0 = all pass; non-zero = at least one failure (details on stderr).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def load_yaml(path: Path):
    with path.open() as fh:
        return yaml.safe_load(fh)


def main() -> int:
    schema_path = ROOT / "install" / "config.schema.json"
    try:
        schema = json.loads(schema_path.read_text())
        Draft202012Validator.check_schema(schema)
        print(f"OK  schema is valid JSON Schema: {schema_path.relative_to(ROOT)}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL schema invalid: {exc}", file=sys.stderr)
        return 1  # nothing else can be checked without a schema

    validator = Draft202012Validator(schema)

    def validate(obj, label: str) -> None:
        errs = sorted(validator.iter_errors(obj), key=lambda e: e.path)
        if errs:
            for e in errs:
                loc = "/".join(str(p) for p in e.path) or "(root)"
                fail(f"{label}: {loc}: {e.message}")
        else:
            print(f"OK  {label} validates against schema")

    # 2. Template config
    tmpl = ROOT / "templates" / "config" / "agentic.config.yml.tmpl"
    try:
        validate(load_yaml(tmpl), tmpl.relative_to(ROOT).as_posix())
    except Exception as exc:  # noqa: BLE001
        fail(f"{tmpl.relative_to(ROOT)}: cannot parse: {exc}")

    # 3. Minimal config
    validate(
        {
            "version": 2,
            "profile": "standard",
            "platform": {"type": "github", "default_branch": "main"},
            "defaults": {"provider": "claude", "models": {"claude": {"default": "c"}}},
        },
        "minimal config",
    )

    # 4. Agent presets
    agents_dir = ROOT / "templates" / "agents"
    for preset in sorted(agents_dir.glob("*.yml")):
        try:
            a = load_yaml(preset)
        except Exception as exc:  # noqa: BLE001
            fail(f"{preset.relative_to(ROOT)}: cannot parse: {exc}")
            continue
        rel = preset.relative_to(ROOT).as_posix()
        if not isinstance(a, dict) or "type" not in a:
            fail(f"{rel}: missing required 'type'")
        skill = (a or {}).get("skill")
        if skill and not (ROOT / "templates" / "skills" / skill).is_dir():
            fail(f"{rel}: references missing skill '{skill}'")
        else:
            print(f"OK  agent preset {preset.name} -> skill '{skill}'")

    # 5. Skills
    skills_dir = ROOT / "templates" / "skills"
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_md.read_text()
        rel = skill_md.relative_to(ROOT).as_posix()
        if not text.startswith("---"):
            fail(f"{rel}: missing YAML frontmatter")
        elif "verdict:" not in text:
            fail(f"{rel}: missing structured 'verdict' output contract")
        else:
            print(f"OK  skill {rel}")

    if errors:
        print(f"\n{len(errors)} validation error(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("\nAll contract validations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
