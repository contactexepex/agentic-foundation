"""Tests for validate_skill_file_existence (issue #198, V-S06).

Covers:
- A stage with skill=None is not checked and no error is raised.
- A stage with a non-existent skill file raises StaticValidationError naming
  the V-S06 code and the expected file path.
- A stage with an existing skill file passes without error.
- A disabled stage (enabled: false) with skill set is skipped — no error.
- Mixed stages: only missing-file stages fail; present-file and no-skill
  stages pass silently.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


def test_v_s06_stage_with_no_skill_raises_no_error() -> None:
    """A stage where skill=None (e.g. an IMPLEMENT stage) never triggers V-S06."""
    from stagr.core.skill_validator import validate_skill_file_existence

    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory)
        stages = [{"id": "implement", "type": "implement"}]
        validate_skill_file_existence(stages, project_root)


def test_v_s06_missing_skill_file_raises_error_with_code() -> None:
    """A stage with a non-existent skill file raises StaticValidationError naming V-S06."""
    from stagr.core.models import StaticValidationError
    from stagr.core.skill_validator import validate_skill_file_existence

    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory)
        stages = [{"id": "review", "skill": "code-review"}]

        raised = False
        try:
            validate_skill_file_existence(stages, project_root)
        except StaticValidationError as error:
            raised = True
            error_message = str(error)
            assert "V-S06" in error_message, (
                f"Error must reference V-S06: {error_message}"
            )
            assert "code-review" in error_message, (
                f"Error must name the missing skill id: {error_message}"
            )
        assert raised, "Expected StaticValidationError for a missing skill file"


def test_v_s06_missing_skill_file_error_names_expected_path() -> None:
    """The V-S06 error message names the exact expected file path that was checked."""
    from stagr.core.models import StaticValidationError
    from stagr.core.skill_validator import validate_skill_file_existence

    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory)
        expected_path = project_root / ".agentic" / "skills" / "code-review" / "SKILL.md"
        stages = [{"id": "review", "skill": "code-review"}]

        raised = False
        try:
            validate_skill_file_existence(stages, project_root)
        except StaticValidationError as error:
            raised = True
            error_message = str(error)
            assert str(expected_path) in error_message, (
                f"Error must contain expected path '{expected_path}': {error_message}"
            )
        assert raised, "Expected StaticValidationError for a missing skill file"


def test_v_s06_existing_skill_file_passes() -> None:
    """A stage whose skill file exists at the expected path raises no error."""
    from stagr.core.skill_validator import validate_skill_file_existence

    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory)
        skill_file = project_root / ".agentic" / "skills" / "code-review" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("---\nid: code-review\n---\n# Code Review\n")

        stages = [{"id": "review", "skill": "code-review"}]
        validate_skill_file_existence(stages, project_root)


def test_v_s06_disabled_stage_with_skill_is_skipped() -> None:
    """A stage with enabled=false and a skill set does not trigger V-S06."""
    from stagr.core.skill_validator import validate_skill_file_existence

    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory)
        stages = [{"id": "review", "skill": "code-review", "enabled": False}]
        # No skill file created — would fail if the disabled stage were checked.
        validate_skill_file_existence(stages, project_root)


def test_v_s06_stage_id_named_in_error() -> None:
    """The V-S06 error message names the stage id of the offending stage."""
    from stagr.core.models import StaticValidationError
    from stagr.core.skill_validator import validate_skill_file_existence

    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory)
        stages = [{"id": "my-review-stage", "skill": "code-review"}]

        raised = False
        try:
            validate_skill_file_existence(stages, project_root)
        except StaticValidationError as error:
            raised = True
            assert "my-review-stage" in str(error), (
                f"Error must name stage id 'my-review-stage': {error}"
            )
        assert raised, "Expected StaticValidationError for a missing skill file"


def test_v_s06_mixed_stages_only_missing_files_fail() -> None:
    """Only the first stage with a missing skill file fails; present-file and no-skill pass."""
    from stagr.core.models import StaticValidationError
    from stagr.core.skill_validator import validate_skill_file_existence

    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory)
        existing_skill_file = project_root / ".agentic" / "skills" / "code-review" / "SKILL.md"
        existing_skill_file.parent.mkdir(parents=True)
        existing_skill_file.write_text("---\nid: code-review\n---\n# ok\n")

        stages = [
            {"id": "implement", "type": "implement"},
            {"id": "review", "skill": "code-review"},
            {"id": "security", "skill": "security-review"},
        ]

        raised = False
        try:
            validate_skill_file_existence(stages, project_root)
        except StaticValidationError as error:
            raised = True
            assert "security-review" in str(error), (
                f"Error must name the missing skill 'security-review': {error}"
            )
        assert raised, "Expected StaticValidationError for the missing security-review skill"


def test_v_s06_empty_stages_passes() -> None:
    """An empty stage list produces no error."""
    from stagr.core.skill_validator import validate_skill_file_existence

    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory)
        validate_skill_file_existence([], project_root)
