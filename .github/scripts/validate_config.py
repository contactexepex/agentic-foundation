#!/usr/bin/env python3
"""Deterministic validation for the agentic-foundation contract.

This is the repository's "green" check (the equivalent of a unit-test suite for a
contract/docs repo). It runs in CI (`validate.yml`) and in the Codex implementor's
validation step. It has no network access and only reads repository files.

Checks:
  1. stagr/config.schema.json is valid JSON Schema (2020-12).
  2. stagr/templates/config/agentic.config.yml.tmpl validates against the schema.
  3. The repo's own .agentic/config.yml validates against the schema (dogfood).
  4. A representative minimal config validates.
  5. Stage-graph invariants the schema cannot express: unique stage ids, every
     `depends_on` names an existing stage, and no dependency cycles.
  6. Every agent preset (stagr/templates/agents/*.yml) is a mapping with a `type` and,
     if it names a `skill`, that skill dir exists.
  7. Every skill (stagr/templates/skills/*/SKILL.md) has parseable YAML frontmatter with
     the required keys and a `verdict:` line inside a fenced code block.

Exit code 0 = all pass; non-zero = at least one failure (details on stderr).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SKILL_REQUIRED_KEYS = {"id", "name", "stage_type", "version"}
errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def load_yaml(path: Path):
    with path.open() as handle:
        return yaml.safe_load(handle)


def check_stage_graph(cfg, label: str) -> None:
    """Unique ids, resolvable depends_on, and acyclicity — not expressible in JSON Schema."""
    if not isinstance(cfg, dict):
        return
    stages = cfg.get("stages")
    if not isinstance(stages, list) or not stages:
        return
    stage_ids: list[str] = []
    dependencies: dict[str, list[str]] = {}
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        stage_id = stage.get("id")
        if not isinstance(stage_id, str):
            continue
        stage_ids.append(stage_id)
        raw_depends = stage.get("depends_on")
        # A schema-invalid but plausible value (e.g. `depends_on: 1`) is reported by the schema
        # validator; guard here so graph checking never crashes on a non-list before that report.
        dependencies[stage_id] = (
            [dep for dep in raw_depends if isinstance(dep, str)] if isinstance(raw_depends, list) else []
        )

    duplicates = sorted({stage_id for stage_id in stage_ids if stage_ids.count(stage_id) > 1})
    if duplicates:
        fail(f"{label}: duplicate stage id(s): {', '.join(duplicates)}")
    known_ids = set(stage_ids)

    # `depends_on` may reference profile-provided stages that a non-`custom` config does not list
    # here (the profile is expanded by the renderer, not by this file). So only enforce that a
    # dependency names an EXISTING stage when the config carries the complete graph (profile: custom).
    # Self-dependency is always invalid; cycle detection below considers only listed edges, so it is
    # safe for any profile.
    complete_graph = cfg.get("profile", "standard") == "custom"
    for stage_id, targets in dependencies.items():
        for target in targets:
            if target == stage_id:
                fail(f"{label}: stage '{stage_id}' depends_on itself")
            elif complete_graph and target not in known_ids:
                fail(f"{label}: stage '{stage_id}' depends_on missing stage '{target}'")

    # Cycle detection over the resolvable edges (DFS with colors).
    UNVISITED, IN_PROGRESS, DONE = 0, 1, 2
    color = {stage_id: UNVISITED for stage_id in known_ids}

    def visit(node: str, path: list[str]) -> None:
        color[node] = IN_PROGRESS
        for neighbor in dependencies.get(node, []):
            if neighbor not in known_ids or neighbor == node:
                continue
            if color[neighbor] == IN_PROGRESS:
                cycle = " -> ".join(path[path.index(neighbor):] + [neighbor]) if neighbor in path \
                    else f"{node} -> {neighbor}"
                fail(f"{label}: dependency cycle: {cycle}")
            elif color[neighbor] == UNVISITED:
                visit(neighbor, path + [neighbor])
        color[node] = DONE

    for stage_id in known_ids:
        if color[stage_id] == UNVISITED:
            visit(stage_id, [stage_id])


def check_skill(skill_md: Path) -> None:
    rel = skill_md.relative_to(ROOT).as_posix()
    text = skill_md.read_text()
    if not text.startswith("---"):
        fail(f"{rel}: missing YAML frontmatter")
        return
    parts = text.split("---", 2)
    if len(parts) < 3:
        fail(f"{rel}: unterminated YAML frontmatter")
        return
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        fail(f"{rel}: frontmatter is not valid YAML: {exc}")
        return
    if not isinstance(meta, dict):
        fail(f"{rel}: frontmatter must be a mapping")
        return
    missing = SKILL_REQUIRED_KEYS - set(meta)
    if missing:
        fail(f"{rel}: frontmatter missing required key(s): {', '.join(sorted(missing))}")
    # `verdict:` must live inside a fenced code block (the structured output contract),
    # not merely be mentioned in prose.
    in_fence = False
    fence_marker = ""
    verdict_in_fence = False
    for line in parts[2].splitlines():
        stripped = line.lstrip()
        # Markdown allows both ``` and ~~~ fences; a fence closes only on its own marker.
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence_marker = True, stripped[0]
            continue
        if in_fence and stripped.startswith(fence_marker * 3):
            in_fence, fence_marker = False, ""
            continue
        if in_fence and re.match(r"\s*verdict:", line):
            verdict_in_fence = True
            break
    if not verdict_in_fence:
        fail(f"{rel}: no `verdict:` line inside a fenced output block")
    if not errors or errors[-1].split(":")[0] != rel:
        print(f"OK  skill {rel}")


def main() -> int:
    schema_path = ROOT / "stagr" / "config.schema.json"
    try:
        schema = json.loads(schema_path.read_text())
        Draft202012Validator.check_schema(schema)
        print(f"OK  schema is valid JSON Schema: {schema_path.relative_to(ROOT)}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL schema invalid: {exc}", file=sys.stderr)
        return 1  # nothing else can be checked without a schema

    validator = Draft202012Validator(schema)

    def validate(obj, label: str) -> None:
        schema_errors = sorted(validator.iter_errors(obj), key=lambda error: list(error.path))
        if schema_errors:
            for error in schema_errors:
                location = "/".join(str(part) for part in error.path) or "(root)"
                fail(f"{label}: {location}: {error.message}")
        else:
            print(f"OK  {label} validates against schema")

    # 2/3. Real config files that must conform to the schema (+ graph invariants).
    for rel in ("stagr/templates/config/agentic.config.yml.tmpl", ".agentic/config.yml"):
        path = ROOT / rel
        if not path.exists():
            fail(f"{rel}: expected file is missing")
            continue
        try:
            cfg = load_yaml(path)
        except Exception as exc:  # noqa: BLE001
            fail(f"{rel}: cannot parse: {exc}")
            continue
        validate(cfg, rel)
        check_stage_graph(cfg, rel)

    # 4. Minimal config.
    validate(
        {
            "version": 2,
            "profile": "standard",
            "platform": {"type": "github", "default_branch": "main"},
            "defaults": {"provider": "claude", "models": {"claude": {"default": "c"}}},
        },
        "minimal config",
    )

    # 6. Agent presets.
    for preset in sorted((ROOT / "stagr" / "templates" / "agents").glob("*.yml")):
        rel = preset.relative_to(ROOT).as_posix()
        try:
            preset_data = load_yaml(preset)
        except Exception as exc:  # noqa: BLE001
            fail(f"{rel}: cannot parse: {exc}")
            continue
        if not isinstance(preset_data, dict):
            fail(f"{rel}: must be a YAML mapping")
            continue
        if "type" not in preset_data:
            fail(f"{rel}: missing required 'type'")
            continue
        skill = preset_data.get("skill")
        if skill and not (ROOT / "stagr" / "templates" / "skills" / skill).is_dir():
            fail(f"{rel}: references missing skill '{skill}'")
            continue
        print(f"OK  agent preset {preset.name}" + (f" -> skill '{skill}'" if skill else " (no skill)"))

    # 7. Skills.
    for skill_md in sorted((ROOT / "stagr" / "templates" / "skills").glob("*/SKILL.md")):
        check_skill(skill_md)

    if errors:
        print(f"\n{len(errors)} validation error(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("\nAll contract validations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
