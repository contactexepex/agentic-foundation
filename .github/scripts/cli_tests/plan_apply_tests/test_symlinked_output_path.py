"""Review finding: `--out` must not reach its directory through a symlink inside the project root."""
from __future__ import annotations

import os

from ..harness import check
from .helpers import DEFAULT_WORKFLOW_DIRECTORY, dogfood_project, run_cli, snapshot_tree


def test_symlinked_ancestor_of_the_default_output_directory_is_refused() -> None:
    """`.github/workflows` (or `.github`) committed as a symlink must never be written through."""
    for symlinked_relative_path in (DEFAULT_WORKFLOW_DIRECTORY, DEFAULT_WORKFLOW_DIRECTORY.parent):
        with dogfood_project() as project_root:
            outside_directory = project_root.parent / f"{project_root.name}-outside"
            outside_directory.mkdir()
            symlink_path = project_root / symlinked_relative_path
            symlink_path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(outside_directory, symlink_path)
            snapshot_before = snapshot_tree(outside_directory)
            for command in ("plan", "apply"):
                exit_code, _, error_output = run_cli(command)
                check(exit_code == 1 and "symlink" in error_output,
                      f"{command}: {symlinked_relative_path} as a symlink is refused (stderr: {error_output.strip()})")
            check(snapshot_tree(outside_directory) == snapshot_before,
                  f"nothing is written through the symlink at {symlinked_relative_path}")


def test_symlinked_custom_output_directory_is_refused_even_outside_the_project_root() -> None:
    """An explicit --out that is itself a symlink is refused, wherever it lives."""
    with dogfood_project() as project_root:
        real_directory = project_root.parent / f"{project_root.name}-real"
        real_directory.mkdir()
        linked_directory = project_root.parent / f"{project_root.name}-link"
        os.symlink(real_directory, linked_directory)
        exit_code, _, error_output = run_cli("apply", "--out", str(linked_directory))
        check(exit_code == 1 and "symlink" in error_output and not any(real_directory.iterdir()),
              f"apply: --out that is a symlink is refused and nothing is written (stderr: {error_output.strip()})")


def test_ordinary_output_directories_still_work() -> None:
    """A plain nested --out inside the project root is unaffected by the symlink guard."""
    with dogfood_project() as project_root:
        exit_code, _, error_output = run_cli("apply", "--out", "build/generated/workflows")
        check(exit_code == 0 and (project_root / "build" / "generated" / "workflows" / "governance.yml").is_file(),
              f"apply: nested plain --out is written (stderr: {error_output.strip()})")
