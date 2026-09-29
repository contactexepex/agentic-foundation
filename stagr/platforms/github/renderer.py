"""GitHubPlatformRenderer: Phase 1, Phase 2a, and Phase 2b artifact generator for GitHub Actions.

Phase 1 (render_stage): translates a (ExecutionPlan, NormalizedStage, RenderContext)
triple into a GitHub Actions workflow file (.github/workflows/stage-<id>.yml) inside
output_dir and returns a StageResultSpec that describes the Check Run this stage will
emit at run time.

Phase 2a (render_routing): generates the routing artifact
(.github/workflows/routing.yml) that classifies each PR head commit as FAST or NORMAL
and publishes a ``RouteClassification`` Check Run authenticated by the Stagr GitHub App.

Phase 2b (render_governance): generates the merge-gate workflow at
.github/workflows/governance.yml.  The workflow reads StageResultSignal values from
Check Runs published by stage execution artifacts, verifies publisher identity against
the Stagr App ID (rendered as a literal constant), and blocks merge when any blocking
stage has a BLOCKED or FAILED conclusion.  See _governance.py for the complete
governance logic specification.

Security invariant (stage workflows): stages with required_secrets (privileged stages)
MUST use ``pull_request_target`` — never ``pull_request``. The ``pull_request`` event
does not expose repository secrets, so any stage that needs them would fail silently.
More critically, ``pull_request_target`` runs with the base-branch workflow definition,
which is crucial for trusted execution. This renderer enforces the invariant at render
time so a misconfiguration is caught before deployment.

Token isolation (stage workflows): the Stagr GitHub App installation token (acquired
in step 1 and used in step 4 for Check Run creation) is NEVER passed to the backend
invocation step (step 3). The backend step receives only the secrets declared in
ExecutionPlan.required_secrets (resolved alias → env_name pairs). Mixing the App token
with backend invocation calls would grant the backend write access to platform
primitives (Check Runs) it must not control.

Stage workflow structure (see stage_workflow.py):
  execute job    1. App token acquisition   — always emitted
                 2. Eligibility check       — trust, fork policy, current head, route, dependencies
                                              (spec: #207); sets the output ``proceed`` that gates
                                              step 3. Runs on the declared triggers and, for a stage
                                              with dependencies, on upstream check_run/check_suite
                                              wake-ups.
                 3. Idempotency guard and   — PR_COMMENT backends (spec: #205): one step checks the
                    backend invocation        completion guard and the in-flight lease, then posts
                                              the comment; holds only the TRUSTED_COMMENTER_TOKEN
                                              secret. Other invocation kinds keep placeholder steps.
                 4. Result signaling        — Check Run carrying the StageResultSignal (spec: #206);
                                              the only step that creates the Check Run
  reconcile job  issue_comment wakeup; updates the Check Run in place (spec: #206)
  sweep job      scheduled backstop over open pull requests (spec: #206); updates only
The reconcile and sweep jobs exist only for plans that declare asynchronous evidence.

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

from stagr.core.enums import InvocationKind, StageResultSignalKind
from stagr.core.models import (
    ExecutionPlan,
    NormalizedStage,
    RenderContext,
    StageResultProvenance,
    StageResultSpec,
)
from stagr.platforms.github._governance import generate_governance_workflow_yaml
from stagr.platforms.github.routing_workflow import (
    generate_routing_workflow_yaml,
    ROUTING_WORKFLOW_FILENAME,
)
from stagr.platforms.github.stage_signal_config import (
    build_stage_check_run_name,
    build_stage_signal_config,
)
from stagr.platforms.github.stage_workflow import build_on_section, build_stage_workflow_yaml


class GitHubPlatformRenderer:
    """PlatformRenderer that generates GitHub Actions workflow YAML files.

    ``SUPPORTED_INVOCATION_KINDS`` declares which ``InvocationKind`` values
    this renderer can translate into GitHub Actions workflow steps.  The static
    validator (V-S08) reads this to ensure no stage backend requires a kind the
    platform cannot handle.

    Phase 1 (render_stage): generates a stage execution workflow file at
    ``output_dir/.github/workflows/stage-<id>.yml`` (or dry-run when
    ``output_dir`` is None) and returns the StageResultSpec.

    Phase 2a (render_routing): generates the routing workflow at
    ``output_dir/.github/workflows/routing.yml`` that classifies PR head commits
    and publishes an authenticated ``RouteClassification`` Check Run.

    Phase 2b (render_governance): generates the merge-gate workflow at
    ``output_dir/.github/workflows/governance.yml``.

    All three methods raise ``ValueError`` in dry-run mode (``output_dir`` is None).
    """

    # GitHub Actions supports all current InvocationKind values: native CI steps
    # (CI_COMPONENT / Actions), pull-request comments (PR_COMMENT), direct API
    # calls from a workflow step (API_CALL), and workflow_dispatch triggers
    # (WORKFLOW_DISPATCH).
    SUPPORTED_INVOCATION_KINDS: frozenset[InvocationKind] = frozenset({
        InvocationKind.PR_COMMENT,
        InvocationKind.API_CALL,
        InvocationKind.CI_COMPONENT,
        InvocationKind.WORKFLOW_DISPATCH,
    })

    # Invocation kinds whose workflow step is a functional backend call. The other supported
    # kinds are accepted by V-S08 but currently render an "Invoke backend (stub)" placeholder
    # step; `stagr plan`/`apply` warn about each stage that uses one so a no-op is never silent.
    FUNCTIONAL_INVOCATION_KINDS: frozenset[InvocationKind] = frozenset({InvocationKind.PR_COMMENT})

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

        Writes ``.github/workflows/stage-<stage.id>.yml`` inside
        ``output_dir`` when not in dry-run mode.  In dry-run mode (``output_dir``
        is None) no file is written and the StageResultSpec is still returned.

        Raises ValueError if the stage is privileged (non-empty
        ``plan.required_secrets``) but any of its triggers cannot be satisfied by
        ``pull_request_target`` — a security invariant violation.
        """
        is_privileged = bool(plan.required_secrets)
        check_run_name = build_stage_check_run_name(stage.id)
        signal_config = build_stage_signal_config(
            plan, stage, render_context, self._publisher_app_id, check_run_name
        )
        on_section_yaml = build_on_section(
            stage.triggers, signal_config.has_asynchronous_evidence, signal_config.has_dependencies
        )
        self._assert_privileged_stage_on_section_is_safe(stage, on_section_yaml, is_privileged)

        workflow_yaml = build_stage_workflow_yaml(
            plan,
            stage,
            signal_config,
            on_section_yaml,
            self._publisher_app_id,
            self._publisher_private_key_secret,
        )

        if self._output_dir is not None:
            workflow_file_path = (
                self._output_dir / ".github" / "workflows" / f"stage-{stage.id}.yml"
            )
            workflow_file_path.parent.mkdir(parents=True, exist_ok=True)
            workflow_file_path.write_text(workflow_yaml, encoding="utf-8")

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

        Generates ``.github/workflows/routing.yml`` inside ``output_dir``.  When
        ``render_context.routing_policy.fast_path`` is ``None``, the workflow
        immediately emits ``RouteClassification=NORMAL`` with no path analysis.
        When a ``FastPathPolicy`` is present, the workflow fetches changed file
        paths, tests them against the configured glob patterns, and emits FAST or
        NORMAL accordingly.

        In both cases the ``RouteClassification`` result is published as an
        authenticated Check Run using the Stagr GitHub App installation token.

        Raises ValueError in dry-run mode (output_dir is None).
        """
        if self._output_dir is None:
            raise ValueError(
                "render_routing cannot be called in dry-run mode (output_dir is None)"
            )
        workflow_yaml = generate_routing_workflow_yaml(
            fast_path_policy=render_context.routing_policy.fast_path,
            publisher_app_id=self._publisher_app_id,
            publisher_private_key_secret=self._publisher_private_key_secret,
        )
        routing_workflow_path = (
            self._output_dir / ".github" / "workflows" / ROUTING_WORKFLOW_FILENAME
        )
        routing_workflow_path.parent.mkdir(parents=True, exist_ok=True)
        routing_workflow_path.write_text(workflow_yaml, encoding="utf-8")

    def render_governance(
        self,
        result_specs: tuple[StageResultSpec, ...],
        render_context: RenderContext,
    ) -> None:
        """Phase 2b: write the governance / merge-gate workflow artifact.

        Generates ``.github/workflows/governance.yml`` inside ``output_dir``.
        The workflow reads StageResultSignal values from Check Runs published
        by stage execution artifacts, verifies that each Check Run was
        published by the Stagr GitHub App (using the publisher_app_id rendered
        as a literal constant), and blocks merge when any blocking stage
        reports a BLOCKED or FAILED conclusion.

        Raises ValueError in dry-run mode (output_dir is None).

        Args:
            result_specs: StageResultSpec for every stage produced in Phase 1.
            render_context: RenderContext carrying MergePolicy, TrustPolicy,
                and RoutingPolicy used to determine blocking stages.
        """
        if self._output_dir is None:
            raise ValueError(
                "render_governance cannot be called in dry-run mode (output_dir is None)"
            )

        governance_yaml = generate_governance_workflow_yaml(
            publisher_app_id=self._publisher_app_id,
            publisher_private_key_secret=self._publisher_private_key_secret,
            result_specs=result_specs,
            render_context=render_context,
        )

        governance_file_path = (
            self._output_dir / ".github" / "workflows" / "governance.yml"
        )
        governance_file_path.parent.mkdir(parents=True, exist_ok=True)
        governance_file_path.write_text(governance_yaml, encoding="utf-8")

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
