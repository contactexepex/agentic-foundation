"""Result signaling, reconciliation, and sweep YAML generators for GitHub stage workflows.

Generates three parts of the stage execution workflow beyond the execute job:
  1. The 'Publish result' step: marks the StageResultSignal Check Run as in_progress
     when the backend is invoked (or completed inline for synchronous stages).
     The final completed state for async stages is set by the reconcile or sweep job.
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

from stagr.core.enums import EvidenceKind, ForkPolicy, GateDispositionKind
from stagr.core.models import ExecutionPlan, RenderContext

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

    For synchronous stages (ALWAYS_PASS gate with no declared evidence), marks
    the Check Run completed/success inline. For async stages (any evidence
    declared), marks the Check Run in_progress; the final completed state is
    written by the reconcile or sweep job after verifying declared evidence.
    """
    check_run_name = f"stagr/stage/{stage_id}"
    is_synchronous = (
        not plan.evidence
        and plan.gate_disposition.kind is GateDispositionKind.ALWAYS_PASS
    )
    if is_synchronous:
        return _build_completed_inline_step(
            stage_id, check_run_name, publisher_app_id, app_token_output_expr
        )
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
    Extracts the PR context, checks whether declared evidence is present for the
    current head SHA, and updates the Check Run only when evidence is present.
    When evidence is absent (backend has not yet posted its result), the job exits
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
    """Return the YAML for the Publish result step (async stages).

    Upserts the Check Run as in_progress when the backend is invoked. The
    reconcile/sweep jobs set the final completed status after confirming
    declared evidence for the current head SHA.
    """
    return (
        f"      - name: Publish result\n"
        f"        env:\n"
        f'          GH_TOKEN: "{app_token_output_expr}"\n'
        f'          HEAD_SHA: "${{{{ github.event.pull_request.head.sha || github.sha }}}}"\n'
        f'          STAGR_APP_ID: "{publisher_app_id}"\n'
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f"          PAYLOAD=$(jq -n \\\n"
        f'            --arg stageId "{stage_id}" \\\n'
        f'            --arg headSha "${{HEAD_SHA}}" \\\n'
        f'            --arg state "running" \\\n'
        f'            --arg conclusion "unknown" \\\n'
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
        f'              -f status=in_progress \\\n'
        f'              --field "output[title]=Stagr: {stage_id}" \\\n'
        f'              --field "output[summary]=${{PAYLOAD}}"\n'
        f"          else\n"
        f"            gh api --method POST \\\n"
        f'              "repos/${{GITHUB_REPOSITORY}}/check-runs" \\\n'
        f'              -f "name={check_run_name}" -f "head_sha=${{HEAD_SHA}}" \\\n'
        f'              -f status=in_progress \\\n'
        f'              --field "output[title]=Stagr: {stage_id}" \\\n'
        f'              --field "output[summary]=${{PAYLOAD}}"\n'
        f"          fi\n"
    )


def _build_completed_inline_step(
    stage_id: str,
    check_run_name: str,
    publisher_app_id: str,
    app_token_output_expr: str,
) -> str:
    """Return the YAML for the Publish result step (synchronous ALWAYS_PASS stages).

    Marks the Check Run completed/success inline in the execute job. Used when
    the gate disposition is ALWAYS_PASS and no evidence is declared, meaning the
    stage completes synchronously without a backend async result to await.
    """
    return (
        f"      - name: Publish result\n"
        f"        env:\n"
        f'          GH_TOKEN: "{app_token_output_expr}"\n'
        f'          HEAD_SHA: "${{{{ github.event.pull_request.head.sha || github.sha }}}}"\n'
        f'          STAGR_APP_ID: "{publisher_app_id}"\n'
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f"          PAYLOAD=$(jq -n \\\n"
        f'            --arg stageId "{stage_id}" \\\n'
        f'            --arg headSha "${{HEAD_SHA}}" \\\n'
        f'            --arg state "completed" \\\n'
        f'            --arg conclusion "pass" \\\n'
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
        f'              -f status=completed -f "conclusion=success" \\\n'
        f'              --field "output[title]=Stagr: {stage_id}" \\\n'
        f'              --field "output[summary]=${{PAYLOAD}}"\n'
        f"          else\n"
        f"            gh api --method POST \\\n"
        f'              "repos/${{GITHUB_REPOSITORY}}/check-runs" \\\n'
        f'              -f "name={check_run_name}" -f "head_sha=${{HEAD_SHA}}" \\\n'
        f'              -f status=completed -f "conclusion=success" \\\n'
        f'              --field "output[title]=Stagr: {stage_id}" \\\n'
        f'              --field "output[summary]=${{PAYLOAD}}"\n'
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


def _build_selector_jq_predicates(selector: str) -> str:
    """Build jq select() predicates for a (possibly compound) selector string.

    Designed for embedding in a SINGLE-QUOTED shell string passed to jq, so
    no shell-level backslash escaping is needed for the double-quotes inside
    the jq expression — the shell passes single-quoted content verbatim.

    The selector is space-separated where:
    - The first token is a literal prefix, checked via contains().
    - Subsequent key=value tokens are treated as JSON field assertions:
      contains('"key":"value"'), matching the literal JSON field in the
      comment body (e.g. "status":"completed" from the security marker JSON).

    Returns jq pipe-chained select() predicates with a leading space and
    trailing pipe, or an empty string when selector is empty.
    """
    parts = selector.split()
    if not parts:
        return ""
    predicates = [f' select(.body | contains("{parts[0]}")) |']
    for token in parts[1:]:
        if "=" in token:
            key, _, value = token.partition("=")
            predicates.append(
                f' select(.body | contains("\\"{key}\\":\\"{value}\\"")) |'
            )
    return "".join(predicates)


def _build_evidence_detection_lines_reconcile(plan: ExecutionPlan) -> str:
    """Return bash lines that detect declared evidence in a reconcile step.

    When evidence is declared, paginates all PR comments and exits 0 when none
    match the declared selector (including compound key=value JSON field checks)
    and the current head SHA. When no evidence is declared, returns an empty
    string (gate eval proceeds immediately).

    Uses gh api --paginate to avoid missing evidence on comment-heavy PRs.
    Compound selectors (space-separated key=value tokens after the prefix) are
    expanded into separate jq predicates so each token is checked individually.

    When EvidenceSpec.github_app_id is set, only comments posted by that GitHub
    App are accepted; this prevents forgery by ordinary commenters.
    """
    if not plan.evidence:
        return ""
    evidence_spec = plan.evidence[0]
    selector_predicates = _build_selector_jq_predicates(evidence_spec.selector)
    app_id_filter = ""
    if evidence_spec.github_app_id is not None:
        app_id_filter = (
            f' select(.performed_via_github_app.id | tostring'
            f' == "{evidence_spec.github_app_id}") |'
        )
    return (
        f'          evidence=$(gh api --paginate "repos/${{GITHUB_REPOSITORY}}/issues/${{pr_number}}/comments" \\\n'
        f"            --jq '.[]' \\\n"
        f"            | jq --arg sha \"${{head_sha}}\" -r \\\n"
        f"            '{app_id_filter}{selector_predicates} select(.body | contains($sha)) | .id' \\\n"
        f"            | head -1)\n"
        f'          if [[ -z "${{evidence}}" ]]; then exit 0; fi\n'
    )


def _build_evidence_detection_lines_sweep(plan: ExecutionPlan, stage_id: str) -> str:
    """Return bash lines that detect declared evidence inside a sweep loop iteration.

    When evidence is declared, paginates all PR comments and continues to the
    next PR when none match the declared selector and HEAD_SHA. When no evidence
    is declared, returns an empty string (gate eval proceeds immediately).

    Uses gh api --paginate to avoid missing evidence on comment-heavy PRs.
    Compound selectors are expanded into separate jq predicates (see
    _build_selector_jq_predicates).

    When EvidenceSpec.github_app_id is set, only comments posted by that GitHub
    App are accepted; this prevents forgery by ordinary commenters.
    """
    if not plan.evidence:
        return ""
    evidence_spec = plan.evidence[0]
    selector_predicates = _build_selector_jq_predicates(evidence_spec.selector)
    app_id_filter = ""
    if evidence_spec.github_app_id is not None:
        app_id_filter = (
            f' select(.performed_via_github_app.id | tostring'
            f' == "{evidence_spec.github_app_id}") |'
        )
    return (
        f'            evidence=$(gh api --paginate "repos/${{GITHUB_REPOSITORY}}/issues/${{pr_number}}/comments" \\\n'
        f"              --jq '.[]' \\\n"
        f"              | jq --arg sha \"${{HEAD_SHA}}\" -r \\\n"
        f"              '{app_id_filter}{selector_predicates} select(.body | contains($sha)) | .id' \\\n"
        f"              | head -1)\n"
        f'            if [[ -z "${{evidence}}" ]]; then continue; fi\n'
    )


def _build_no_open_threads_gate_eval_reconcile(plan: ExecutionPlan) -> str:
    """Return bash lines for NO_OPEN_THREADS gate evaluation in the reconcile step.

    Uses the declared FindingScopeSpec to filter threads by author and, when
    scope.head_sha is True, by commit OID via pullRequestReview.commit.oid.
    """
    scope = plan.gate_disposition.scope
    created_by = scope.created_by if scope is not None else ""
    filter_by_head_sha = scope is not None and scope.head_sha

    if filter_by_head_sha:
        gql_query = (
            "            -f query='"
            "query($owner:String!,$repo:String!,$pr:Int!)"
            "{repository(owner:$owner,name:$repo)"
            "{pullRequest(number:$pr)"
            "{reviewThreads(first:100){nodes{isResolved,"
            "comments(first:1){nodes{author{login},"
            "pullRequestReview{commit{oid}}}}}}}}}' \\\n"
        )
        jq_head_sha_arg = ' --arg head_sha "${head_sha}"'
        head_sha_jq_filter = (
            "\n             | select(.comments.nodes[0].pullRequestReview.commit.oid == $head_sha)"
        )
    else:
        gql_query = (
            "            -f query='"
            "query($owner:String!,$repo:String!,$pr:Int!)"
            "{repository(owner:$owner,name:$repo)"
            "{pullRequest(number:$pr)"
            "{reviewThreads(first:100){nodes{isResolved,"
            "comments(first:1){nodes{author{login}}}}}}}}"  "' \\\n"
        )
        jq_head_sha_arg = ""
        head_sha_jq_filter = ""

    return (
        f"          thread_count=$(gh api graphql \\\n"
        + gql_query
        + f'            -f owner="${{GITHUB_REPOSITORY_OWNER}}" \\\n'
        + f'            -f repo="${{GITHUB_REPOSITORY#*/}}" \\\n'
        + f'            -F pr="${{pr_number}}" \\\n'
        + f"            | jq --arg author \"{created_by}\"{jq_head_sha_arg} \\\n"
        + "            '[.data.repository.pullRequest.reviewThreads.nodes[]\n"
        + "             | select(.isResolved == false)\n"
        + "             | select($author == \"\" or\n"
        + "               .comments.nodes[0].author.login == $author)"
        + head_sha_jq_filter
        + "]\n"
        + "            | length')\n"
        + f'          if [[ "${{thread_count}}" -gt 0 ]]; then\n'
        + f'            conclusion_native="action_required"; conclusion_payload="blocked"\n'
        + "          else\n"
        + f'            conclusion_native="success"; conclusion_payload="pass"\n'
        + "          fi\n"
    )


def _build_no_open_threads_gate_eval_sweep(plan: ExecutionPlan) -> str:
    """Return bash lines for NO_OPEN_THREADS gate evaluation in the sweep step.

    Uses the declared FindingScopeSpec to filter threads by author and, when
    scope.head_sha is True, by commit OID via pullRequestReview.commit.oid.
    The sweep uses HEAD_SHA (uppercase) as the shell variable.
    """
    scope = plan.gate_disposition.scope
    findings_author = scope.created_by if scope is not None and scope.created_by else ""
    filter_by_head_sha = scope is not None and scope.head_sha

    if filter_by_head_sha:
        gql_query = (
            "            -f query='"
            "query($owner:String!,$repo:String!,$pr:Int!)"
            "{repository(owner:$owner,name:$repo)"
            "{pullRequest(number:$pr)"
            "{reviewThreads(first:100){nodes{isResolved,"
            "comments(first:1){nodes{author{login},"
            "pullRequestReview{commit{oid}}}}}}}}}' \\\n"
        )
        jq_head_sha_arg = ' --arg head_sha "${HEAD_SHA}"'
        head_sha_jq_filter = (
            "\n             | select(.comments.nodes[0].pullRequestReview.commit.oid == $head_sha)"
        )
    else:
        gql_query = (
            "            -f query='"
            "query($owner:String!,$repo:String!,$pr:Int!)"
            "{repository(owner:$owner,name:$repo)"
            "{pullRequest(number:$pr)"
            "{reviewThreads(first:100){nodes{isResolved,"
            "comments(first:1){nodes{author{login}}}}}}}}"  "' \\\n"
        )
        jq_head_sha_arg = ""
        head_sha_jq_filter = ""

    return (
        f"          thread_count=$(gh api graphql \\\n"
        + gql_query
        + f'            -f owner="${{GITHUB_REPOSITORY_OWNER}}" \\\n'
        + f'            -f repo="${{GITHUB_REPOSITORY#*/}}" \\\n'
        + f'            -F pr="${{pr_number}}" \\\n'
        + f"            | jq --arg author \"{findings_author}\"{jq_head_sha_arg} \\\n"
        + "            '[.data.repository.pullRequest.reviewThreads.nodes[]\n"
        + "             | select(.isResolved == false)\n"
        + "             | select($author == \"\" or\n"
        + "               .comments.nodes[0].author.login == $author)"
        + head_sha_jq_filter
        + "]\n"
        + "            | length')\n"
        + f'          if [[ "${{thread_count}}" -gt 0 ]]; then\n'
        + f'            conclusion_native="action_required"; conclusion_payload="blocked"\n'
        + "          else\n"
        + f'            conclusion_native="success"; conclusion_payload="pass"\n'
        + "          fi\n"
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
    verifies declared evidence: only comments whose body matches the declared
    selector prefix and current head SHA are accepted. If absent, exits without
    touching any Check Run. If present, re-evaluates the gate disposition and
    upserts the Check Run with output.title and output.summary.
    """
    evidence_lines = _build_evidence_detection_lines_reconcile(plan)
    if gate_kind is GateDispositionKind.NO_OPEN_THREADS:
        gate_eval_lines = _build_no_open_threads_gate_eval_reconcile(plan)
    else:
        gate_eval_lines = f'          conclusion_native="success"; conclusion_payload="pass"\n'

    return (
        f"      - name: Reconcile stage result\n"
        f"        env:\n"
        f'          GH_TOKEN: "${{{{ steps.app-token.outputs.token }}}}"\n'
        f'          STAGR_APP_ID: "{publisher_app_id}"\n'
        f'          STAGE_ID: "{stage_id}"\n'
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f'          if [[ "${{GITHUB_EVENT_NAME}}" == "issue_comment" ]]; then\n'
        f'            is_pr=$(jq -r \'.issue.pull_request != null\' "${{GITHUB_EVENT_PATH}}")\n'
        f'            if [[ "${{is_pr}}" != "true" ]]; then exit 0; fi\n'
        f"          fi\n"
        f"          # Resolve PR number from the event\n"
        f'          if [[ "${{GITHUB_EVENT_NAME}}" == "issue_comment" ]]; then\n'
        f'            pr_number=$(jq -r .issue.number "${{GITHUB_EVENT_PATH}}")\n'
        f"          else\n"
        f'            pr_number=$(jq -r ".check_suite.pull_requests[0].number // empty" "${{GITHUB_EVENT_PATH}}")\n'
        f"          fi\n"
        f'          if [[ -z "${{pr_number}}" ]]; then exit 0; fi\n'
        f"          # Fetch current head SHA from PR API (never trust event payload)\n"
        f'          head_sha=$(gh api "repos/${{GITHUB_REPOSITORY}}/pulls/${{pr_number}}" --jq .head.sha)\n'
        f"{evidence_lines}"
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
        f'              --field "output[title]=Stagr: {stage_id}" \\\n'
        f'              --field "output[summary]=${{PAYLOAD}}"\n'
        f"          else\n"
        f"            gh api --method POST \\\n"
        f'              "repos/${{GITHUB_REPOSITORY}}/check-runs" \\\n'
        f'              -f "name={check_run_name}" -f "head_sha=${{HEAD_SHA}}" \\\n'
        f'              -f status=completed -f "conclusion=${{conclusion_native}}" \\\n'
        f'              --field "output[title]=Stagr: {stage_id}" \\\n'
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
    declared evidence before re-evaluating gate disposition, then upserts the
    Check Run with output.title and output.summary for each eligible PR.
    """
    fork_check = (
        f'          head_repo_id=$(echo "${{pr_json}}" | jq -r .head.repo.id)\n'
        f'          base_repo_id=$(echo "${{pr_json}}" | jq -r .base.repo.id)\n'
        f'          if [[ "${{head_repo_id}}" != "${{base_repo_id}}" ]]; then continue; fi\n'
        if deny_forks else ""
    )
    evidence_check = _build_evidence_detection_lines_sweep(plan, stage_id)
    if gate_kind is GateDispositionKind.NO_OPEN_THREADS:
        gate_eval = _build_no_open_threads_gate_eval_sweep(plan)
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
        f'                --field "output[title]=Stagr: {stage_id}" \\\n'
        f'                --field "output[summary]=${{PAYLOAD}}"\n'
        f"            else\n"
        f"              gh api --method POST \\\n"
        f'                "repos/${{GITHUB_REPOSITORY}}/check-runs" \\\n'
        f'                -f "name={check_run_name}" -f "head_sha=${{HEAD_SHA}}" \\\n'
        f'                -f status=completed -f "conclusion=${{conclusion_native}}" \\\n'
        f'                --field "output[title]=Stagr: {stage_id}" \\\n'
        f'                --field "output[summary]=${{PAYLOAD}}"\n'
        f"            fi\n"
        f"          done <<< \"${{prs}}\"\n"
    )
