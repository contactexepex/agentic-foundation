"""Stage workflow assembly for GitHubPlatformRenderer (issues #194 scaffold and #206 runtime).

Builds the text of ``.github/workflows/stage-<id>.yml``. One workflow file per stage holds up to
three jobs, each guarded by an explicit ``github.event_name`` condition so that a wakeup can never
re-run a backend and an invocation trigger can never run the sweep:

- ``execute``   declared triggers (PR events, manual, issue label). The eligibility step is a stub
                owned by #207. For a ``PR_COMMENT`` backend one step (#205) checks the completion
                guard and the in-flight lease and posts the invocation, holding only the backend
                secret; other invocation kinds keep placeholder steps. The last step publishes the
                result signal through the shared runtime (#206) and is the ONLY place a Check Run
                is created.
- ``reconcile`` ``issue_comment`` wakeup for a pull request, only when the comment author is a
                declared evidence producer. Updates an existing Check Run in place.
- ``sweep``     scheduled backstop over every open pull request. Updates in place.

``reconcile`` and ``sweep`` exist only for plans that declare asynchronous evidence; a plan that
completes inside the execute job has nothing to observe later. Neither holds the backend secret, so
neither can post an invocation: an expired in-flight lease is recovered the next time ``execute``
runs (see design-docs/08-github-codex-mapping.md).

All per-stage data reaches the runtime as one JSON document in the workflow ``env`` (see
``stage_signal_config``); the runtime source is embedded once and run with ``python3 -c``.
"""
from __future__ import annotations

from pathlib import Path

from stagr.core.enums import StageTrigger
from stagr.core.models import ExecutionPlan, NormalizedStage
from stagr.platforms.github.stage_signal_config import StageSignalConfig

# Pinned commit SHA for actions/create-github-app-token v1.11.1. Update this SHA after
# auditing the release when upgrading. Mutable tags are not used per AGENTS.md supply-chain
# integrity requirement (immutable action pinning).
APP_TOKEN_ACTION_REF = (
    "actions/create-github-app-token@a6de09a5e3e8eb40028eda38d7ad96aea41ac75e"
    "  # v1.11.1"
)

RUNTIME_SCRIPT_PATH = Path(__file__).parent / "runtime" / "stage_signal_runtime.py"

# Sweep cadence (design-doc 06 suggests every five minutes; five is also GitHub's minimum).
SWEEP_CRON_SCHEDULE = "*/5 * * * *"

_PULL_REQUEST_TARGET_EVENTS_FOR_PR_OPENED = ("opened", "reopened", "ready_for_review")
_PULL_REQUEST_TARGET_EVENTS_FOR_PR_UPDATED = ("synchronize",)

_APP_TOKEN_OUTPUT_EXPRESSION = "${{ steps.app-token.outputs.token }}"
_RUN_RUNTIME_COMMAND = 'python3 -c "$STAGR_RUNTIME_SCRIPT"'


def build_on_section(
    stage_triggers: tuple[StageTrigger, ...], has_asynchronous_evidence: bool
) -> str:
    """Return the indented YAML lines for the ``on:`` trigger section.

    Merges PR_OPENED and PR_UPDATED into a single pull_request_target block when both are present.
    MANUAL becomes workflow_dispatch and ISSUE_LABELED becomes an issues block. Reconciliation
    wakeups (``issue_comment`` and the scheduled sweep) are renderer-internal, not StageTriggers,
    and are added only when the plan declares asynchronous evidence.
    """
    pull_request_target_events: list[str] = []
    include_workflow_dispatch = False
    issues_events: list[str] = []

    for trigger in stage_triggers:
        if trigger is StageTrigger.PR_OPENED:
            pull_request_target_events.extend(_PULL_REQUEST_TARGET_EVENTS_FOR_PR_OPENED)
        elif trigger is StageTrigger.PR_UPDATED:
            pull_request_target_events.extend(_PULL_REQUEST_TARGET_EVENTS_FOR_PR_UPDATED)
        elif trigger is StageTrigger.MANUAL:
            include_workflow_dispatch = True
        elif trigger is StageTrigger.ISSUE_LABELED:
            issues_events.append("labeled")

    lines: list[str] = []
    if pull_request_target_events:
        lines.append("  pull_request_target:\n")
        lines.append(f"    types: [{', '.join(pull_request_target_events)}]\n")
    if include_workflow_dispatch:
        lines.append("  workflow_dispatch:\n")
    if issues_events:
        lines.append("  issues:\n")
        lines.append(f"    types: [{', '.join(issues_events)}]\n")
    if has_asynchronous_evidence:
        lines.append("  issue_comment:\n")
        lines.append("    types: [created, edited]\n")
        lines.append("  schedule:\n")
        lines.append(f'    - cron: "{SWEEP_CRON_SCHEDULE}"\n')
    return "".join(lines)


def build_stage_workflow_yaml(
    plan: ExecutionPlan,
    stage: NormalizedStage,
    signal_config: StageSignalConfig,
    on_section: str,
    publisher_app_id: str,
    private_key_secret_name: str,
) -> str:
    """Return the complete GitHub Actions workflow YAML string for the stage."""
    token_step = _build_token_acquisition_step(publisher_app_id, private_key_secret_name)
    jobs = [_build_execute_job(plan, stage, signal_config, token_step)]
    if signal_config.has_asynchronous_evidence:
        jobs.append(_build_reconcile_job(signal_config, token_step))
        jobs.append(_build_sweep_job(token_step))
    return (
        f'name: "Stagr stage: {stage.id}"\n'
        "\n"
        "on:\n"
        f"{on_section}"
        "\n"
        "concurrency:\n"
        f'  group: "stagr-{stage.id}-{_build_concurrency_key_expression()}"\n'
        "  cancel-in-progress: false\n"
        "\n"
        f"{_build_workflow_env(signal_config)}"
        "\n"
        "jobs:\n"
        + "\n".join(jobs)
    )


def _build_concurrency_key_expression() -> str:
    """Per-pull-request key for events; a repository-wide key for the scheduled sweep (#194)."""
    return (
        "${{ github.event_name == 'schedule' && 'sweep'"
        " || github.event.pull_request.number || github.event.issue.number }}"
    )


def _build_workflow_env(signal_config: StageSignalConfig) -> str:
    runtime_script = RUNTIME_SCRIPT_PATH.read_text(encoding="utf-8")
    return (
        "env:\n"
        "  STAGR_STAGE_CONFIG: |\n"
        f"    {signal_config.to_json_text()}\n"
        "  STAGR_RUNTIME_SCRIPT: |\n"
        f"{_indent_block(runtime_script, '    ')}"
    )


def _indent_block(text: str, indentation: str) -> str:
    """Indent every non-blank line; blank lines stay empty so the YAML block scalar is stable."""
    return "".join(
        (f"{indentation}{line}" if line.strip() else "") + "\n" for line in text.splitlines()
    )


def _build_token_acquisition_step(publisher_app_id: str, private_key_secret_name: str) -> str:
    private_key_expression = f"${{{{ secrets.{private_key_secret_name} }}}}"
    return (
        "      - name: Acquire Stagr App installation token\n"
        "        id: app-token\n"
        f"        uses: {APP_TOKEN_ACTION_REF}\n"
        "        with:\n"
        f'          app-id: "{publisher_app_id}"\n'
        f'          private-key: "{private_key_expression}"\n'
    )


def _declared_event_names(stage: NormalizedStage) -> list[str]:
    event_name_by_trigger = {
        StageTrigger.PR_OPENED: "pull_request_target",
        StageTrigger.PR_UPDATED: "pull_request_target",
        StageTrigger.MANUAL: "workflow_dispatch",
        StageTrigger.ISSUE_LABELED: "issues",
    }
    declared = {event_name_by_trigger[trigger] for trigger in stage.triggers}
    return [name for name in ("pull_request_target", "workflow_dispatch", "issues") if name in declared]


def _build_execute_job(
    plan: ExecutionPlan,
    stage: NormalizedStage,
    signal_config: StageSignalConfig,
    token_step: str,
) -> str:
    event_conditions = [f"github.event_name == '{name}'" for name in _declared_event_names(stage)]
    execute_condition = " || ".join(event_conditions) or "false"
    return (
        "  execute:\n"
        f'    if: "${{{{ {execute_condition} }}}}"\n'
        "    runs-on: ubuntu-latest\n"
        "    permissions:\n"
        "      pull-requests: read\n"
        "      contents: read\n"
        "    steps:\n"
        f"{token_step}"
        "\n"
        "      - name: Check eligibility (stub)\n"
        "        run: echo 'Eligibility check placeholder (spec:#207)'\n"
        "\n"
        f"{_build_invocation_steps(plan, signal_config)}"
        "\n"
        "      - name: Publish result signal\n"
        '        if: "${{ !cancelled() }}"\n'
        "        env:\n"
        f'          GH_TOKEN: "{_APP_TOKEN_OUTPUT_EXPRESSION}"\n'
        "          STAGR_MODE: publish\n"
        '          STAGR_PULL_NUMBER: "${{ github.event.pull_request.number }}"\n'
        '          STAGR_EVENT_HEAD_SHA: "${{ github.event.pull_request.head.sha }}"\n'
        '          STAGR_JOB_STATUS: "${{ job.status }}"\n'
        f"        run: {_RUN_RUNTIME_COMMAND}\n"
    )


def _build_invocation_steps(plan: ExecutionPlan, signal_config: StageSignalConfig) -> str:
    """Return the step(s) that ask the backend to run.

    A ``PR_COMMENT`` backend gets the real ``invoke`` step (#205): one process checks the
    completion guard and the in-flight lease, then posts the comment, so a skipped invocation is
    simply a step that exits successfully and the publish step still runs. Other invocation kinds
    are not implemented by this renderer yet and keep the placeholder steps.
    """
    if not signal_config.posts_pull_request_comment_invocation:
        return (
            "      - name: Check idempotency (stub)\n"
            "        run: echo 'Idempotency guard placeholder (only PR_COMMENT backends are guarded)'\n"
            "\n"
            "      - name: Invoke backend (stub)\n"
            "        run: echo 'Backend invocation placeholder (only PR_COMMENT backends are invoked)'\n"
            f"{_build_backend_env_section(plan, ())}"
        )
    invoke_environment_lines = (
        "          STAGR_MODE: invoke\n",
        '          STAGR_PULL_NUMBER: "${{ github.event.pull_request.number }}"\n',
        '          STAGR_EVENT_HEAD_SHA: "${{ github.event.pull_request.head.sha }}"\n',
    )
    return (
        "      - name: Invoke backend (idempotent)\n"
        f"{_build_backend_env_section(plan, invoke_environment_lines)}"
        f"        run: {_RUN_RUNTIME_COMMAND}\n"
    )


def _build_backend_env_section(plan: ExecutionPlan, leading_lines: tuple[str, ...]) -> str:
    """Return the YAML env block for the backend invocation step.

    Emits ``leading_lines`` (already indented) and then one line per resolved SecretRef, mapping
    alias -> secrets.<env_name>. Returns an empty string when there is nothing to emit. The App
    token is never part of this block.
    """
    if not plan.required_secrets and not leading_lines:
        return ""
    lines = ["        env:\n", *leading_lines]
    for secret_ref in plan.required_secrets:
        secret_expression = f"${{{{ secrets.{secret_ref.env_name} }}}}"
        lines.append(f'          {secret_ref.alias}: "{secret_expression}"\n')
    return "".join(lines)


def _build_reconcile_job(signal_config: StageSignalConfig, token_step: str) -> str:
    producer_conditions = " || ".join(
        f"github.event.comment.user.login == '{producer}'"
        for producer in signal_config.evidence_producers
    )
    wakeup_condition = (
        "github.event_name == 'issue_comment' && github.event.issue.pull_request"
        f" && ({producer_conditions})"
    )
    return (
        "  reconcile:\n"
        f'    if: "${{{{ {wakeup_condition} }}}}"\n'
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 10\n"
        "    permissions: {}\n"
        "    steps:\n"
        f"{token_step}"
        "\n"
        "      - name: Reconcile result signal\n"
        "        env:\n"
        f'          GH_TOKEN: "{_APP_TOKEN_OUTPUT_EXPRESSION}"\n'
        "          STAGR_MODE: reconcile\n"
        '          STAGR_PULL_NUMBER: "${{ github.event.issue.number }}"\n'
        f"        run: {_RUN_RUNTIME_COMMAND}\n"
    )


def _build_sweep_job(token_step: str) -> str:
    return (
        "  sweep:\n"
        "    if: \"${{ github.event_name == 'schedule' }}\"\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 10\n"
        "    permissions: {}\n"
        "    steps:\n"
        f"{token_step}"
        "\n"
        "      - name: Sweep open pull requests\n"
        "        env:\n"
        f'          GH_TOKEN: "{_APP_TOKEN_OUTPUT_EXPRESSION}"\n'
        "          STAGR_MODE: sweep\n"
        f"        run: {_RUN_RUNTIME_COMMAND}\n"
    )
