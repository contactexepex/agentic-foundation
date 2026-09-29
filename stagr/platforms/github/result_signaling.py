"""Result signaling, reconciliation, and sweep YAML generators for GitHub stage workflows.

Generates three parts of the stage execution workflow beyond the execute job:
  1. The 'Publish result' step: marks the StageResultSignal Check Run as in_progress
     when the backend is invoked (replacing the stub from issue #194). The final
     completed state is set by the reconcile or sweep job after confirming evidence.
  2. The 'reconcile' job: re-evaluates gate disposition on issue_comment and
     check_suite wakeup events.
  3. The 'sweep' job: re-evaluates all eligible open PRs on the scheduled sweep trigger.

StageResultSignal <-> GitHub Check Run mapping:
  StageResultState.COMPLETED | FAILED  -> Check Run status:     completed
  StageResultConclusion.PASS           -> conclusion: success,  payload: "pass"
  StageResultConclusion.BLOCKED        -> conclusion: action_required, payload: "blocked"
  StageResultConclusion.FAILED         -> conclusion: failure,  payload: "failed"
  StageResultConclusion.UNKNOWN        -> conclusion: neutral,  payload: "unknown"

The JSON payload in output.summary is the authoritative signal source for consumers:
  {"schemaVersion": 1, "stageId": "...", "headSha": "...", "state": "...", "conclusion": "..."}
"""
from __future__ import annotations

from stagr.core.enums import ForkPolicy, GateDispositionKind
from stagr.core.models import ExecutionPlan, FindingScopeSpec, RenderContext

# Pinned commit SHA for actions/create-github-app-token v1.11.1.
_APP_TOKEN_ACTION_REF = (
    "actions/create-github-app-token@a6de09a5e3e8eb40028eda38d7ad96aea41ac75e"
    "  # v1.11.1"
)

_SIGNAL_SCHEMA_VERSION = 1


def generate_result_signaling_step(
    plan: ExecutionPlan,
    stage_id: str,
    publisher_app_id: str,
    app_token_output_expr: str,
) -> str:
    """Return the 'Publish result' step YAML for the execute job.

    Marks the Check Run as in_progress when the backend is invoked. The
    final completed state (pass or blocked) is written by the reconcile or
    sweep job after it verifies backend-posted evidence for the current head SHA.
    """
    check_run_name = f"stagr/stage/{stage_id}"
    return _build_in_progress_step(
        stage_id, check_run_name, publisher_app_id, app_token_output_expr
    )


def generate_reconcile_job(
    stage_id: str,
    publisher_app_id: str,
    private_key_secret_expr: str,
    plan: ExecutionPlan,
) -> str:
    """Return the YAML for the 'reconcile' job.

    Runs on issue_comment (created/edited) and check_suite (completed) events.
    Extracts the PR context, checks whether evidence is present for the current
    head SHA, and updates the Check Run only when evidence is present. When
    evidence is absent (backend has not yet posted its result), the job exits
    without modifying any Check Run, satisfying the acceptance criterion:
    "Evidence absent on reconciliation wakeup -> no Check Run updated."
    """
    check_run_name = f"stagr/stage/{stage_id}"
    gate_kind = plan.gate_disposition.kind
    token_step = _build_token_acquisition_step(publisher_app_id, private_key_secret_expr)
    reconcile_step = _build_reconcile_step(stage_id, check_run_name, publisher_app_id, gate_kind, plan)
    return (
        f"  reconcile:\n"
        f"    runs-on: ubuntu-latest\n"
        f"    if: github.event_name == 'issue_comment' || github.event_name == 'check_suite'\n"
        f"    permissions:\n"
        f"      pull-requests: read\n"
        f"      contents: read\n"
        f"    steps:\n"
        f"{token_step}"
        f"\n"
        f"{reconcile_step}"
    )


def generate_sweep_job(
    stage_id: str,
    publisher_app_id: str,
    private_key_secret_expr: str,
    plan: ExecutionPlan,
    render_context: RenderContext,
) -> str:
    """Return the YAML for the 'sweep' job.

    Runs on the scheduled cron trigger. Enumerates all open PRs and filters by
    TrustPolicy (author_association) and ForkPolicy (head.repo.id vs base.repo.id).
    Trusted_roles and fork_policy are baked as literal constants at render time so
    the sweep step requires no external config fetch at runtime.
    """
    check_run_name = f"stagr/stage/{stage_id}"
    trusted_roles_csv = ",".join(
        role.value for role in render_context.trust_policy.trusted_roles
    )
    deny_forks = render_context.trust_policy.fork_policy is ForkPolicy.DENY
    token_step = _build_token_acquisition_step(publisher_app_id, private_key_secret_expr)
    sweep_step = _build_sweep_step(
        stage_id, check_run_name, publisher_app_id, plan.gate_disposition.kind,
        trusted_roles_csv, deny_forks, plan
    )
    return (
        f"  sweep:\n"
        f"    runs-on: ubuntu-latest\n"
        f"    if: github.event_name == 'schedule'\n"
        f"    permissions:\n"
        f"      pull-requests: read\n"
        f"      contents: read\n"
        f"    steps:\n"
        f"{token_step}"
        f"\n"
        f"{sweep_step}"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_in_progress_step(
    stage_id: str,
    check_run_name: str,
    publisher_app_id: str,
    app_token_output_expr: str,
) -> str:
    """Return the YAML for the Publish result step.

    Upserts the Check Run as in_progress when the backend is invoked. The
    reconcile/sweep jobs set the final completed status after confirming
    backend-posted evidence for the current head SHA.
    """
    return (
        f"      - name: Publish result\n"
        f"        env:\n"
        f'          GH_TOKEN: "{app_token_output_expr}"\n'
        f'          HEAD_SHA: "${{{{ github.event.pull_request.head.sha || github.sha }}}}"\n'
        f'          STAGR_APP_ID: "{publisher_app_id}"\n'
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f"          existing_id=$(gh api \\\n"
        f'            "repos/${{GITHUB_REPOSITORY}}/commits/${{HEAD_SHA}}'
        f"/check-runs?check_name={check_run_name}&filter=all&per_page=2\" \\\n"
        f'            | jq --arg app_id "${{STAGR_APP_ID}}"'
        f" '[.check_runs[] | select(.app.id | tostring == $app_id)][0].id // empty')\n"
        f'          if [[ -n "${{existing_id}}" ]]; then\n'
        f"            gh api --method PATCH \\\n"
        f'              "repos/${{GITHUB_REPOSITORY}}/check-runs/${{existing_id}}" \\\n'
        f"              -f status=in_progress\n"
        f"          else\n"
        f"            gh api --method POST \\\n"
        f'              "repos/${{GITHUB_REPOSITORY}}/check-runs" \\\n'
        f'              -f "name={check_run_name}" -f "head_sha=${{HEAD_SHA}}" \\\n'
        f"              -f status=in_progress\n"
        f"          fi\n"
    )


def _build_token_acquisition_step(publisher_app_id: str, private_key_secret_expr: str) -> str:
    """Return the YAML block for App installation token acquisition (reused across jobs)."""
    return (
        f"      - name: Acquire Stagr App installation token\n"
        f"        id: app-token\n"
        f"        uses: {_APP_TOKEN_ACTION_REF}\n"
        f"        with:\n"
        f'          app-id: "{publisher_app_id}"\n'
        f'          private-key: "{private_key_secret_expr}"\n'
    )


def _build_reconcile_step(
    stage_id: str,
    check_run_name: str,
    publisher_app_id: str,
    gate_kind: GateDispositionKind,
    plan: ExecutionPlan,
) -> str:
    """Return the YAML for the reconcile step within the reconcile job.

    Extracts the PR number from the event, fetches the current head SHA, then
    verifies evidence: only comments posted by the publisher App
    (performed_via_github_app.id matches STAGR_APP_ID) containing the stage
    anchor and current head SHA are accepted. If absent, exits without touching
    any Check Run. If present, re-evaluates the gate disposition and upserts.
    """
    if gate_kind is GateDispositionKind.NO_OPEN_THREADS:
        scope = plan.gate_disposition.scope
        created_by = scope.created_by if scope is not None else ""
        gate_eval_lines = (
            f"          thread_count=$(gh api graphql \\\n"
            f"            -f query='"
            f"query($owner:String!,$repo:String!,$pr:Int!){{"
            f"repository(owner:$owner,name:$repo){{"
            f"pullRequest(number:$pr){{"
            f"reviewThreads(first:100){{nodes{{isResolved,"
            f"comments(first:1){{nodes{{author{{login}}}}}}}}}}}}}}}}}}' \\\n"
            f'            -f owner="${{GITHUB_REPOSITORY_OWNER}}" \\\n'
            f'            -f repo="${{GITHUB_REPOSITORY#*/}}" \\\n'
            f'            -F pr="${{pr_number}}" \\\n'
            f"            | jq --arg author \"{created_by}\" \\\n"
            "            '[.data.repository.pullRequest.reviewThreads.nodes[]\n"
            "             | select(.isResolved == false)\n"
            "             | select($author == \"\" or\n"
            "               .comments.nodes[0].author.login == $author)]\n"
            "            | length')\n"
            f'          if [[ "${{thread_count}}" -gt 0 ]]; then\n'
            f'            conclusion_native="action_required"; conclusion_payload="blocked"\n'
            f"          else\n"
            f'            conclusion_native="success"; conclusion_payload="pass"\n'
            f"          fi\n"
        )
    else:
        gate_eval_lines = (
            f'          conclusion_native="success"; conclusion_payload="pass"\n'
        )
    return (
        f"      - name: Reconcile stage result\n"
        f"        env:\n"
        f'          GH_TOKEN: "${{{{ steps.app-token.outputs.token }}}}"\n'
        f'          STAGR_APP_ID: "{publisher_app_id}"\n'
        f'          STAGE_ID: "{stage_id}"\n'
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f"          # Resolve PR number from the event\n"
        f'          if [[ "${{GITHUB_EVENT_NAME}}" == "issue_comment" ]]; then\n'
        f'            pr_number=$(jq -r .issue.number "${{GITHUB_EVENT_PATH}}")\n'
        f"          else\n"
        f'            pr_number=$(jq -r ".check_suite.pull_requests[0].number // empty" "${{GITHUB_EVENT_PATH}}")\n'
        f"          fi\n"
        f'          if [[ -z "${{pr_number}}" ]]; then exit 0; fi\n'
        f"          # Fetch current head SHA from PR API (never trust event payload)\n"
        f'          head_sha=$(gh api "repos/${{GITHUB_REPOSITORY}}/pulls/${{pr_number}}" --jq .head.sha)\n'
        f"          # Verify evidence: accept only comments posted by the publisher App\n"
        f'          evidence=$(gh api "repos/${{GITHUB_REPOSITORY}}/issues/${{pr_number}}/comments" \\\n'
        f"            --jq \".[] | select(.performed_via_github_app.id | tostring == \\\"${{STAGR_APP_ID}}\\\") |"
        f" select(.body | contains(\\\"stagr-stage-{stage_id}\\\")) |"
        f" select(.body | contains(\\\"${{head_sha}}\\\")) | .id\" | head -1)\n"
        f'          if [[ -z "${{evidence}}" ]]; then exit 0; fi\n'
        f"          HEAD_SHA=${{head_sha}}\n"
        f"{gate_eval_lines}"
        f"          PAYLOAD=$(jq -n \\\n"
        f'            --arg stageId "{stage_id}" \\\n'
        f'            --arg headSha "${{HEAD_SHA}}" \\\n'
        f'            --arg state "completed" \\\n'
        f'            --arg conclusion "${{conclusion_payload}}" \\\n'
        f'            --argjson schemaVersion {_SIGNAL_SCHEMA_VERSION} \\\n'
        f"            '{{schemaVersion: $schemaVersion, stageId: $stageId,"
        f" headSha: $headSha, state: $state, conclusion: $conclusion}}')\n"
        f"          existing_id=$(gh api \\\n"
        f'            "repos/${{GITHUB_REPOSITORY}}/commits/${{HEAD_SHA}}'
        f"/check-runs?check_name={check_run_name}&filter=all&per_page=2\" \\\n"
        f'            | jq --arg app_id "${{STAGR_APP_ID}}"'
        f" '[.check_runs[] | select(.app.id | tostring == $app_id)][0].id // empty')\n"
        f'          if [[ -n "${{existing_id}}" ]]; then\n'
        f"            gh api --method PATCH \\\n"
        f'              "repos/${{GITHUB_REPOSITORY}}/check-runs/${{existing_id}}" \\\n'
        f'              -f status=completed -f "conclusion=${{conclusion_native}}" \\\n'
        f'              --field "output[summary]=${{PAYLOAD}}"\n'
        f"          else\n"
        f"            gh api --method POST \\\n"
        f'              "repos/${{GITHUB_REPOSITORY}}/check-runs" \\\n'
        f'              -f "name={check_run_name}" -f "head_sha=${{HEAD_SHA}}" \\\n'
        f'              -f status=completed -f "conclusion=${{conclusion_native}}" \\\n'
        f'              --field "output[summary]=${{PAYLOAD}}"\n'
        f"          fi\n"
    )


def _build_sweep_step(
    stage_id: str,
    check_run_name: str,
    publisher_app_id: str,
    gate_kind: GateDispositionKind,
    trusted_roles_csv: str,
    deny_forks: bool,
    plan: ExecutionPlan,
) -> str:
    """Return the YAML for the sweep step within the sweep job.

    Enumerates open PRs, filters by author_association (trusted_roles baked at
    render time) and fork policy (deny_forks baked at render time), verifies
    backend-posted evidence before re-evaluating gate disposition, then upserts
    the Check Run for each eligible PR that has evidence.
    """
    fork_check = (
        f'          head_repo_id=$(echo "${{pr_json}}" | jq -r .head.repo.id)\n'
        f'          base_repo_id=$(echo "${{pr_json}}" | jq -r .base.repo.id)\n'
        f'          if [[ "${{head_repo_id}}" != "${{base_repo_id}}" ]]; then continue; fi\n'
        if deny_forks else ""
    )
    evidence_check = (
        f'            evidence=$(gh api "repos/${{GITHUB_REPOSITORY}}/issues/${{pr_number}}/comments" \\\n'
        f"              --jq \".[] | select(.performed_via_github_app.id | tostring == \\\"${{STAGR_APP_ID}}\\\") |"
        f" select(.body | contains(\\\"stagr-stage-{stage_id}\\\")) |"
        f" select(.body | contains(\\\"${{HEAD_SHA}}\\\")) | .id\" | head -1)\n"
        f'            if [[ -z "${{evidence}}" ]]; then continue; fi\n'
    )
    if gate_kind is GateDispositionKind.NO_OPEN_THREADS:
        scope = plan.gate_disposition.scope
        findings_author = scope.created_by if scope is not None and scope.created_by else ""
        gate_eval = (
            f"          thread_count=$(gh api graphql \\\n"
            f"            -f query='"
            f"query($owner:String!,$repo:String!,$pr:Int!){{"
            f"repository(owner:$owner,name:$repo){{"
            f"pullRequest(number:$pr){{"
            f"reviewThreads(first:100){{nodes{{isResolved,"
            f"comments(first:1){{nodes{{author{{login}}}}}}}}}}}}}}}}}}' \\\n"
            f'            -f owner="${{GITHUB_REPOSITORY_OWNER}}" \\\n'
            f'            -f repo="${{GITHUB_REPOSITORY#*/}}" \\\n'
            f'            -F pr="${{pr_number}}" \\\n'
            f"            | jq --arg author \"{findings_author}\" \\\n"
            "            '[.data.repository.pullRequest.reviewThreads.nodes[]\n"
            "             | select(.isResolved == false)\n"
            "             | select($author == \"\" or\n"
            "               .comments.nodes[0].author.login == $author)]\n"
            "            | length')\n"
            f'          if [[ "${{thread_count}}" -gt 0 ]]; then\n'
            f'            conclusion_native="action_required"; conclusion_payload="blocked"\n'
            f"          else\n"
            f'            conclusion_native="success"; conclusion_payload="pass"\n'
            f"          fi\n"
        )
    else:
        gate_eval = f'          conclusion_native="success"; conclusion_payload="pass"\n'
    return (
        f"      - name: Sweep open PRs and reconcile stage results\n"
        f"        env:\n"
        f'          GH_TOKEN: "${{{{ steps.app-token.outputs.token }}}}"\n'
        f'          STAGR_APP_ID: "{publisher_app_id}"\n'
        f'          TRUSTED_ROLES: "{trusted_roles_csv}"\n'
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f'          prs=$(gh api "repos/${{GITHUB_REPOSITORY}}/pulls?state=open&per_page=100" --jq .[])\n'
        f'          while IFS= read -r pr_json; do\n'
        f'            [[ -z "${{pr_json}}" ]] && continue\n'
        f'            author_assoc=$(echo "${{pr_json}}" | jq -r .author_association | tr A-Z a-z)\n'
        f'            if [[ ",${{TRUSTED_ROLES}}," != *",${{author_assoc}},"* ]]; then continue; fi\n'
        f"{fork_check}"
        f'            pr_number=$(echo "${{pr_json}}" | jq -r .number)\n'
        f'            HEAD_SHA=$(echo "${{pr_json}}" | jq -r .head.sha)\n'
        f"{evidence_check}"
        f"{gate_eval}"
        f"            PAYLOAD=$(jq -n \\\n"
        f'              --arg stageId "{stage_id}" \\\n'
        f'              --arg headSha "${{HEAD_SHA}}" \\\n'
        f'              --arg state "completed" \\\n'
        f'              --arg conclusion "${{conclusion_payload}}" \\\n'
        f'              --argjson schemaVersion {_SIGNAL_SCHEMA_VERSION} \\\n'
        f"              '{{schemaVersion: $schemaVersion, stageId: $stageId,"
        f" headSha: $headSha, state: $state, conclusion: $conclusion}}')\n"
        f"            existing_id=$(gh api \\\n"
        f'              "repos/${{GITHUB_REPOSITORY}}/commits/${{HEAD_SHA}}'
        f"/check-runs?check_name={check_run_name}&filter=all&per_page=2\" \\\n"
        f'              | jq --arg app_id "${{STAGR_APP_ID}}"'
        f" '[.check_runs[] | select(.app.id | tostring == $app_id)][0].id // empty')\n"
        f'            if [[ -n "${{existing_id}}" ]]; then\n'
        f"              gh api --method PATCH \\\n"
        f'                "repos/${{GITHUB_REPOSITORY}}/check-runs/${{existing_id}}" \\\n'
        f'                -f status=completed -f "conclusion=${{conclusion_native}}" \\\n'
        f'                --field "output[summary]=${{PAYLOAD}}"\n'
        f"            else\n"
        f"              gh api --method POST \\\n"
        f'                "repos/${{GITHUB_REPOSITORY}}/check-runs" \\\n'
        f'                -f "name={check_run_name}" -f "head_sha=${{HEAD_SHA}}" \\\n'
        f'                -f status=completed -f "conclusion=${{conclusion_native}}" \\\n'
        f'                --field "output[summary]=${{PAYLOAD}}"\n'
        f"            fi\n"
        f"          done <<< \"${{prs}}\"\n"
    )
