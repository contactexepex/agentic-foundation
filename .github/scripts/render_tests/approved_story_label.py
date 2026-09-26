"""Approved-story issue-label trigger tests for the implement stage.

Issue #73: labeling an issue with the configured approved-story label starts the implementer
while keeping workflow_dispatch as a parallel entry point.

Covers:
  * the rendered implementor.yml contains both triggers (issues/labeled + workflow_dispatch);
  * the job condition references the approved-story label;
  * a custom approved_story label value renders correctly;
  * an unsafe (injection-containing) label is rejected at render and at the front door.
"""
from __future__ import annotations

import yaml

from .harness import check, expect_raises, render

# A minimal config that renders the implementer workflow.
_IMPL_CFG = {
    "version": 2,
    "profile": "custom",
    "platform": {"type": "github", "default_branch": "main"},
    "defaults": {"provider": "anthropic", "models": {"anthropic": {"default": "claude-sonnet-4-5"}}},
    "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"}}],
}


def test_approved_story_label_trigger() -> None:
    # Default label name is "approved-story".
    impl_wf = render.render_all(_IMPL_CFG, "github")["implementor.yml"]
    doc = yaml.safe_load(impl_wf)

    # workflow_dispatch is still present (acceptance criterion: dispatch still works).
    on_block = doc.get("on", doc.get(True))
    check("workflow_dispatch" in on_block,
          "label-trigger: workflow_dispatch is still present alongside the label trigger")

    # issues: [labeled] trigger is emitted.
    check("issues" in on_block,
          "label-trigger: issues trigger block is present in rendered implementor.yml")
    issues_block = on_block.get("issues", {})
    check("labeled" in (issues_block.get("types") or []),
          "label-trigger: issues trigger type includes 'labeled'")

    # The job condition references the approved-story label.
    job = doc["jobs"]["implement"]
    job_if = job.get("if", "")
    check("approved-story" in str(job_if),
          "label-trigger: job condition references the default 'approved-story' label")
    check("workflow_dispatch" in str(job_if),
          "label-trigger: job condition also covers workflow_dispatch event")

    # Custom label name renders correctly.
    custom_cfg = {
        **_IMPL_CFG,
        "platform": {**_IMPL_CFG["platform"], "labels": {"approved_story": "story-ready"}},
    }
    custom_wf = render.render_all(custom_cfg, "github")["implementor.yml"]
    check("story-ready" in custom_wf,
          "label-trigger: custom approved_story label value rendered into implementor.yml")

    # An unsafe label (containing a GitHub expression opener) is rejected at render and the front door.
    expr = "${{ github.token }}"
    bad_cfg = {
        **_IMPL_CFG,
        "platform": {**_IMPL_CFG["platform"], "labels": {"approved_story": expr}},
    }
    expect_raises(lambda: render.render_all(bad_cfg, "github"),
                  "label-trigger: approved_story label with ${{}} expression rejected at render")
    expect_raises(lambda: render.validate_config(bad_cfg),
                  "label-trigger: approved_story label with ${{}} expression rejected at front door")
