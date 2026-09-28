"""GitHubPlatformRenderer: Phase 1 stage execution artifact generator for GitHub Actions.

Translates a (ExecutionPlan, NormalizedStage, RenderContext) triple into a GitHub
Actions workflow file (.github/workflows/stagr-stage-<id>.yml) and returns a
StageResultSpec that describes the Check Run this stage will emit at run time.

Security invariant: stages with required_secrets (privileged stages) MUST use
``pull_request_target`` — never ``pull_request``. The ``pull_request`` event does
not expose repository secrets, so any stage that needs them would fail silently.
More critically, ``pull_request_target`` runs with the base-branch workflow
definition, which is crucial for trusted execution. This renderer enforces the
invariant at render time so a misconfiguration is caught before deployment.

Token isolation: the Stagr GitHub App installation token (acquired in step 1 and
used in step 5 for Check Run creation) is NEVER passed to the backend invocation
step (step 4). The backend step uses TRUSTED_COMMENTER_TOKEN exclusively. Mixing
the App token with backend invocation calls would grant the backend write access
to platform primitives (Check Runs) it must not control.

Workflow structure (Phase 1 scaffold; steps 2–5 are stubs awaiting later issues):
  1. App token acquisition   — this issue; always emitted
  2. Eligibility check       — stub (spec: #207)
  3. Idempotency guard       — stub (spec: #205)
  4. Backend invocation      — stub (spec: #205); uses TRUSTED_COMMENTER_TOKEN
  5. Result signaling        — stub (spec: #206); uses App token for Check Run

Trigger mapping (design-doc 08):
  StageTrigger.PR_OPENED    → pull_request_target: [opened, reopened, ready_for_review]
  StageTrigger.PR_UPDATED   → pull_request_target: [synchronize]
  StageTrigger.MANUAL       → workflow_dispatch
  StageTrigger.ISSUE_LABELED → issues: [labeled]

Dry-run mode: when ``output_dir`` is ``None``, ``render_stage`` returns a
StageResultSpec without writing any files. ``render_routing`` and
``render_governance`` raise ``ValueError`` in dry-run mode.
"""
from __future__ import annotations

from pathlib import Path

from stagr.core.enums import StageResultSignalKind, StageTrigger
from stagr.core.models import (
    ExecutionPlan,
    NormalizedStage,
    RenderContext,
    StageResultProvenance,
    StageResultSpec,
)

# Check Run name template — design-doc 08: stagr/stage/<stageId>
_CHECK_RUN_NAME_PREFIX = "stagr/stage"

# GitHub Actions event names for each StageTrigger value.
_PULL_REQUEST_TARGET_EVENTS_FOR_PR_OPENED = ("opened", "reopened", "ready_for_review")
_PULL_REQUEST_TARGET_EVENTS_FOR_PR_UPDATED = ("synchronize",)

# Secret alias used by the backend invocation step (issued by BackendRenderer).
_TRUSTED_COMMENTER_TOKEN_SECRET_ALIAS = "TRUSTED_COMMENTER_TOKEN"


class GitHubPlatformRenderer:
    """PlatformRenderer that generates GitHub Actions workflow YAML files.

    Phase 1 (render_stage): generates a stage execution workflow file at
    ``output_dir/.github/workflows/stagr-stage-<id>.yml`` (or dry-run when
    ``output_dir`` is None) and returns the StageResultSpec.

    Phase 2 (render_routing, render_governance): raises ValueError in dry-run
    mode; full implementation is out of scope for issue #194.
    """

    def __init__(
        self,
        output_dir: Path | None,
        publisher_app_id: str,
        publisher_private_key_secret: str,
    ) -> None:
        """Initialise the renderer.

        Args:
            output_dir: Filesystem path where generated workflow files are written.
                        ``None`` activates dry-run mode — StageResultSpec is
                        returned but no files are written.
            publisher_app_id: Numeric GitHub App ID for the Stagr publisher App,
                              rendered as a literal into the token-acquisition step.
            publisher_private_key_secret: Name of the repository secret that holds
                              the App's RSA private key (e.g. ``STAGR_APP_PRIVATE_KEY``).
                              Rendered as ``${{ secrets.<name> }}`` in the workflow.
        """
        self._output_dir = output_dir
        self._publisher_app_id = publisher_app_id
        self._publisher_private_key_secret = publisher_private_key_secret

    # ------------------------------------------------------------------
    # PlatformRenderer Protocol — Phase 1
    # ------------------------------------------------------------------

    def render_stage(
        self,
        plan: ExecutionPlan,
        stage: NormalizedStage,
        render_context: RenderContext,
    ) -> StageResultSpec:
        """Generate the stage execution workflow and return its StageResultSpec.

        Writes ``.github/workflows/stagr-stage-<stage.id>.yml`` inside
        ``output_dir`` when not in dry-run mode.  In dry-run mode (``output_dir``
        is None) no file is written and the StageResultSpec is still returned.

        Raises ValueError if the stage is privileged (non-empty
        ``plan.required_secrets``) but any of its triggers cannot be satisfied by
        ``pull_request_target`` — a security invariant violation.
        """
        is_privileged = bool(plan.required_secrets)
        on_section_yaml = self._build_on_section(stage.triggers)
        self._assert_privileged_stage_on_section_is_safe(stage, on_section_yaml, is_privileged)

        workflow_yaml = self._generate_workflow_yaml(stage, on_section_yaml)

        if self._output_dir is not None:
            workflow_file_path = self._output_dir / f"stagr-stage-{stage.id}.yml"
            workflow_file_path.write_text(workflow_yaml, encoding="utf-8")

        check_run_name = f"{_CHECK_RUN_NAME_PREFIX}/{stage.id}"
        return StageResultSpec(
            stage_id=stage.id,
            signal_kind=StageResultSignalKind.CHECK_RUN,
            signal_selector=check_run_name,
            provenance=StageResultProvenance(
                publisher_identity=self._publisher_app_id,
            ),
        )

    # ------------------------------------------------------------------
    # PlatformRenderer Protocol — Phase 2 (stubs)
    # ------------------------------------------------------------------

    def render_routing(self, render_context: RenderContext) -> None:
        """Phase 2a: write the routing artifact.

        Raises ValueError in dry-run mode (output_dir is None).
        Full implementation is out of scope for issue #194.
        """
        if self._output_dir is None:
            raise ValueError(
                "render_routing cannot be called in dry-run mode (output_dir is None)"
            )

    def render_governance(
        self,
        result_specs: tuple[StageResultSpec, ...],
        render_context: RenderContext,
    ) -> None:
        """Phase 2b: write the governance artifact.

        Raises ValueError in dry-run mode (output_dir is None).
        Full implementation is out of scope for issue #194.
        """
        if self._output_dir is None:
            raise ValueError(
                "render_governance cannot be called in dry-run mode (output_dir is None)"
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assert_privileged_stage_on_section_is_safe(
        self,
        stage: NormalizedStage,
        on_section_yaml: str,
        is_privileged: bool,
    ) -> None:
        """Raise ValueError if a privileged stage's on-section would use pull_request.

        A privileged stage (non-empty required_secrets) MUST use pull_request_target
        — never the bare pull_request event — because only pull_request_target runs
        with base-branch secrets; pull_request runs in the fork context where secrets
        are unavailable. This renderer's trigger mapping always emits
        pull_request_target for PR triggers; this check is a defence-in-depth guard
        that catches any future change in the mapping that would introduce
        pull_request for a privileged stage.

        Raises ValueError when a bare ``pull_request:`` line appears in
        ``on_section_yaml`` for a privileged stage.
        """
        if not is_privileged:
            return
        for line in on_section_yaml.splitlines():
            stripped = line.strip()
            if stripped == "pull_request:" or stripped.startswith("pull_request: "):
                raise ValueError(
                    f"Security invariant violated: privileged stage '{stage.id}' "
                    f"(non-empty required_secrets) must use pull_request_target, "
                    f"not pull_request. A pull_request trigger does not expose "
                    f"base-branch secrets, so secret-dependent steps would silently "
                    f"fail. Fix the trigger mapping for StageTrigger values on this "
                    f"stage, or remove the required_secrets from the ExecutionPlan."
                )

    def _generate_workflow_yaml(self, stage: NormalizedStage, on_section: str) -> str:
        """Return the complete GitHub Actions workflow YAML string for the stage."""
        concurrency_group = (
            f"stagr-{stage.id}-"
            "${{ github.event.pull_request.number || github.event.issue.number }}"
        )
        private_key_expr = f"${{{{ secrets.{self._publisher_private_key_secret} }}}}"
        app_token_output_expr = "${{ steps.app-token.outputs.token }}"
        trusted_commenter_expr = "${{ secrets.TRUSTED_COMMENTER_TOKEN }}"

        return (
            f'name: "Stagr stage: {stage.id}"\n'
            f"\n"
            f"on:\n"
            f"{on_section}"
            f"\n"
            f"concurrency:\n"
            f'  group: "stagr-{stage.id}-'
            f'${{{{ github.event.pull_request.number || github.event.issue.number }}}}"\n'
            f"  cancel-in-progress: false\n"
            f"\n"
            f"jobs:\n"
            f"  execute:\n"
            f"    runs-on: ubuntu-latest\n"
            f"    permissions:\n"
            f"      checks: write\n"
            f"      pull-requests: read\n"
            f"      contents: read\n"
            f"    steps:\n"
            f"      - name: Acquire Stagr App installation token\n"
            f"        id: app-token\n"
            f"        uses: actions/create-github-app-token@v1\n"
            f"        with:\n"
            f"          app-id: \"{self._publisher_app_id}\"\n"
            f"          private-key: \"{private_key_expr}\"\n"
            f"\n"
            f"      - name: Check eligibility (stub)\n"
            f"        run: echo 'Eligibility check placeholder (spec:#207)'\n"
            f"\n"
            f"      - name: Check idempotency (stub)\n"
            f"        run: echo 'Idempotency guard placeholder (spec:#205)'\n"
            f"\n"
            f"      - name: Invoke backend (stub)\n"
            f"        run: echo 'Backend invocation placeholder (spec:#205)'\n"
            f"        env:\n"
            f"          TRUSTED_COMMENTER_TOKEN: \"{trusted_commenter_expr}\"\n"
            f"\n"
            f"      - name: Publish result (stub)\n"
            f"        run: echo 'Result signaling placeholder (spec:#206)'\n"
            f"        env:\n"
            f"          STAGR_APP_TOKEN: \"{app_token_output_expr}\"\n"
        )

    def _build_on_section(self, stage_triggers: tuple[StageTrigger, ...]) -> str:
        """Return the indented YAML lines for the ``on:`` trigger section.

        Merges PR_OPENED and PR_UPDATED into a single pull_request_target block when
        both are present. MANUAL becomes workflow_dispatch. ISSUE_LABELED becomes
        an issues block.
        """
        pull_request_target_events: list[str] = []
        include_workflow_dispatch = False
        issues_events: list[str] = []

        for trigger in stage_triggers:
            if trigger is StageTrigger.PR_OPENED:
                pull_request_target_events.extend(
                    _PULL_REQUEST_TARGET_EVENTS_FOR_PR_OPENED
                )
            elif trigger is StageTrigger.PR_UPDATED:
                pull_request_target_events.extend(
                    _PULL_REQUEST_TARGET_EVENTS_FOR_PR_UPDATED
                )
            elif trigger is StageTrigger.MANUAL:
                include_workflow_dispatch = True
            elif trigger is StageTrigger.ISSUE_LABELED:
                issues_events.append("labeled")

        lines: list[str] = []

        if pull_request_target_events:
            events_csv = ", ".join(pull_request_target_events)
            lines.append(f"  pull_request_target:\n")
            lines.append(f"    types: [{events_csv}]\n")

        if include_workflow_dispatch:
            lines.append(f"  workflow_dispatch:\n")

        if issues_events:
            events_csv = ", ".join(issues_events)
            lines.append(f"  issues:\n")
            lines.append(f"    types: [{events_csv}]\n")

        return "".join(lines)
