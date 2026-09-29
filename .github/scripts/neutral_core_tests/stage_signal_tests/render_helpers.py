"""Helpers that render real plans into stage workflows for the render-side tests."""
from __future__ import annotations

import dataclasses
from typing import Any

import yaml

from neutral_core_tests.github_platform_renderer_tests.helpers import (
    build_render_context,
    build_renderer,
    build_stage,
)
from stagr.core.enums import StageKind, StageTrigger
from stagr.core.models import ExecutionPlan, NormalizedStage, SecretRef
from stagr.core.renderers.openai_codex_backend_renderer import OpenAICodexBackendRenderer

TRUSTED_COMMENTER_ENV_NAME = "REMEDIATION_TOKEN"


def build_codex_plan(stage_kind: StageKind = StageKind.REVIEW) -> tuple[ExecutionPlan, NormalizedStage]:
    """The real Codex plan for a stage, with the alias resolved as Phase 1 would."""
    stage = dataclasses.replace(build_stage(stage_id=stage_kind.value), kind=stage_kind)
    plan = OpenAICodexBackendRenderer().render(stage)
    resolved_secrets = tuple(
        SecretRef(alias=secret.alias, env_name=TRUSTED_COMMENTER_ENV_NAME)
        for secret in plan.required_secrets
    )
    return dataclasses.replace(plan, required_secrets=resolved_secrets), stage


def render_workflow_text(
    plan: ExecutionPlan, stage: NormalizedStage, render_context: Any = None
) -> str:
    stage_render = build_renderer().render_stage(plan, stage, render_context or build_render_context(stage))
    return stage_render.artifact.content


def parse_workflow(workflow_text: str) -> dict[str, Any]:
    """Parse the workflow; PyYAML reads the ``on`` key as boolean True, so it is renamed."""
    document = yaml.safe_load(workflow_text)
    document["on"] = document.pop(True)
    return document


def render_codex_workflow(
    stage_kind: StageKind = StageKind.REVIEW,
    triggers: tuple[StageTrigger, ...] | None = None,
) -> tuple[str, dict[str, Any]]:
    plan, stage = build_codex_plan(stage_kind)
    if triggers is not None:
        stage = dataclasses.replace(stage, triggers=triggers)
    workflow_text = render_workflow_text(plan, stage)
    return workflow_text, parse_workflow(workflow_text)
