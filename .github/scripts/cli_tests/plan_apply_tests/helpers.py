"""Shared fixtures for the `stagr plan` / `stagr apply` tests.

Every test runs inside a throw-away project directory (also the CWD, because stagr confines the
config path to the project root) that holds a copy of the repository's own `.agentic/` contract,
so the tests exercise the dogfood config end to end.
"""
from __future__ import annotations

import hashlib
import io
import shutil
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, Iterator

import yaml

from ..harness import REPO_ROOT, _project_dir, cli

# Files the GitHub renderer writes for the dogfood config: one workflow per ENABLED stage
# (implement-codex is disabled), plus the routing and governance artifacts.
DOGFOOD_ENABLED_STAGE_IDS = ("implement-claude", "review", "security")
DOGFOOD_WORKFLOW_NAMES = (
    "governance.yml",
    "routing.yml",
    *(f"stage-{stage_id}.yml" for stage_id in DOGFOOD_ENABLED_STAGE_IDS),
)
DEFAULT_WORKFLOW_DIRECTORY = Path(".github") / "workflows"
# First line of every workflow Stagr generates for a stage; only such files may be pruned.
GENERATED_STAGE_HEADER = 'name: "Stagr stage: removed-stage"\n'


@contextmanager
def dogfood_project() -> Iterator[Path]:
    """A temp project (and CWD) containing a copy of the repo's `.agentic/` directory."""
    with _project_dir() as project_root:
        shutil.copytree(REPO_ROOT / ".agentic", project_root / ".agentic")
        yield project_root


def read_config(project_root: Path) -> dict[str, Any]:
    return yaml.safe_load((project_root / ".agentic" / "config.yml").read_text(encoding="utf-8"))


def rewrite_config(project_root: Path, mutate_config: Callable[[dict[str, Any]], None]) -> None:
    """Load the project's config, let `mutate_config` change it in place, and save it back."""
    config = read_config(project_root)
    mutate_config(config)
    (project_root / ".agentic" / "config.yml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def run_cli(*argv: str) -> tuple[int, str, str]:
    """Run `stagr <argv>` in-process and return (exit code, stdout, stderr)."""
    captured_stdout, captured_stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
        exit_code = cli.main(list(argv))
    return exit_code, captured_stdout.getvalue(), captured_stderr.getvalue()


def snapshot_tree(root: Path) -> dict[str, tuple[int, int]]:
    """Every path under `root` mapped to (mtime in ns, size); a missing root is an empty snapshot."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): (path.stat().st_mtime_ns, path.stat().st_size if path.is_file() else -1)
        for path in sorted(root.rglob("*"))
    }


def sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes_by_name(directory: Path) -> dict[str, str]:
    """SHA-256 of every workflow file in `directory`, keyed by file name."""
    return {path.name: sha256_of_file(path) for path in sorted(directory.glob("*.yml"))}


def line_mentioning(output: str, text: str) -> str:
    """The first output line containing `text`, or an empty string."""
    return next((line for line in output.splitlines() if text in line), "")


def hashes_listed_in_plan_output(plan_output: str) -> dict[str, str]:
    """Parse `<name>  <n> bytes  sha256:<hex>` lines from `stagr plan` output."""
    listed_hashes: dict[str, str] = {}
    for line in plan_output.splitlines():
        if "sha256:" in line:
            name = line.split()[2]
            listed_hashes[name] = line.rsplit("sha256:", 1)[1].strip()
    return listed_hashes
