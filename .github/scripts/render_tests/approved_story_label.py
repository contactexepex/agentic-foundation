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

    # A label containing a single quote must be rejected — the approved-story label is used in a
    # single-quoted GitHub expression (`== '{{ approved_story_label }}'`) so a single quote in the
    # label value would break the expression or enable injection.
    sq_cfg = {
        **_IMPL_CFG,
        "platform": {**_IMPL_CFG["platform"], "labels": {"approved_story": "story' OR 1=1"}},
    }
    expect_raises(lambda: render.render_all(sq_cfg, "github"),
                  "label-trigger: approved_story label with single quote rejected at render")
    expect_raises(lambda: render.validate_config(sq_cfg),
                  "label-trigger: approved_story label with single quote rejected at front door")

    # Conditional trigger: when triggers explicitly excludes issue_labeled, the issues block is absent.
    manual_only_cfg = {
        **_IMPL_CFG,
        "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"},
                    "triggers": ["manual"]}],
    }
    manual_wf = render.render_all(manual_only_cfg, "github")["implementor.yml"]
    manual_doc = yaml.safe_load(manual_wf)
    manual_on = manual_doc.get("on", manual_doc.get(True))
    check("issues" not in (manual_on or {}),
          "label-trigger: issues trigger absent when triggers=[manual] (no issue_labeled)")
    check("workflow_dispatch" in (manual_on or {}),
          "label-trigger: workflow_dispatch still present when triggers=[manual]")
    manual_job_if = manual_doc["jobs"]["implement"].get("if", "")
    check("workflow_dispatch" in str(manual_job_if),
          "label-trigger: job condition covers workflow_dispatch when triggers=[manual]")
    check("label.name" not in str(manual_job_if),
          "label-trigger: job condition omits label check when triggers=[manual]")

    # Conditional trigger: when triggers explicitly excludes manual, workflow_dispatch is absent.
    issue_only_cfg = {
        **_IMPL_CFG,
        "stages": [{"id": "implement", "type": "implement", "backend": {"name": "claude-code-action"},
                    "triggers": ["issue_labeled"]}],
    }
    issue_wf = render.render_all(issue_only_cfg, "github")["implementor.yml"]
    issue_doc = yaml.safe_load(issue_wf)
    issue_on = issue_doc.get("on", issue_doc.get(True))
    check("workflow_dispatch" not in (issue_on or {}),
          "label-trigger: workflow_dispatch absent when triggers=[issue_labeled] (P1 regression guard)")
    check("issues" in (issue_on or {}),
          "label-trigger: issues trigger still present when triggers=[issue_labeled]")
    issue_job_if = issue_doc["jobs"]["implement"].get("if", "")
    check("label.name" in str(issue_job_if),
          "label-trigger: job condition covers label check when triggers=[issue_labeled]")
    check("workflow_dispatch" not in str(issue_job_if),
          "label-trigger: job condition omits workflow_dispatch arm when triggers=[issue_labeled]")
