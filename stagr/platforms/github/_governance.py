"""Governance workflow YAML generator for GitHubPlatformRenderer.

Phase 2b: generates the merge-gate workflow artifact that reads
StageResultSignal values from Check Runs published by stage execution
artifacts, verifies publisher identity against the rendered Stagr App ID,
and blocks merge when any blocking stage has a BLOCKED or FAILED conclusion.

Security invariants maintained by the generated workflow:
- Publisher verification: only Check Runs whose app.id equals the Stagr App
  ID (rendered as a literal constant) are trusted.  A Check Run from any
  other GitHub App or GITHUB_TOKEN actor is rejected.
- Fail-closed on duplicates: when more than one Check Run matches a stage's
  signal selector on the current head SHA, merge is blocked and an explicit
  error naming the stage and head SHA is surfaced.
- Signal deserialization from output.summary: state and conclusion are read
  from the JSON payload in the Check Run's output.summary field (not from
  the native status/conclusion fields), and schemaVersion is validated first.
- Head SHA binding: only signals whose headSha matches the current PR head
  commit are accepted; stale signals for prior commits are ignored.
"""
from __future__ import annotations

from stagr.core.models import RenderContext, StageResultSpec

# Expected schemaVersion in the StageResultSignal JSON payload stored in
# a Check Run's output.summary field.  Must match the version emitted by
# stage execution artifacts at run time.
_EXPECTED_STAGE_RESULT_SIGNAL_SCHEMA_VERSION = "1"

# Pinned commit SHA for actions/create-github-app-token v1.11.1.  Update
# after auditing the release when upgrading.  Mutable tags are prohibited
# per AGENTS.md supply-chain integrity requirement.
_APP_TOKEN_ACTION_REF = (
    "actions/create-github-app-token@a6de09a5e3e8eb40028eda38d7ad96aea41ac75e"
    "  # v1.11.1"
)

# Width of the indentation block for run: | script content in the generated
# YAML (offset from the left edge of the file).
_YAML_SCRIPT_LINE_INDENT = "          "


def generate_governance_workflow_yaml(
    publisher_app_id: str,
    publisher_private_key_secret: str,
    result_specs: tuple[StageResultSpec, ...],
    render_context: RenderContext,
) -> str:
    """Return the complete governance workflow YAML string.

    Renders the publisher_app_id as a literal constant so the generated
    workflow can verify publisher identity at run time without any
    additional configuration.  The private_key_secret is referenced by
    name only (never inlined).

    Args:
        publisher_app_id: Numeric Stagr GitHub App ID rendered as a literal
            for both token acquisition and publisher-identity verification.
        publisher_private_key_secret: Name of the repository secret that
            holds the App RSA private key.
        result_specs: StageResultSpec for every stage produced in Phase 1.
        render_context: RenderContext carrying MergePolicy (used to derive
            which stages are blocking).
    """
    private_key_expr = "${{ secrets." + publisher_private_key_secret + " }}"
    app_token_output_expr = "${{ steps.app-token.outputs.token }}"
    pr_head_sha_expr = (
        "${{ github.event.pull_request.head.sha"
        " || github.event.check_suite.head_sha }}"
    )
    pr_number_expr = (
        "${{ github.event.pull_request.number"
        " || github.event.check_suite.pull_requests[0].number }}"
    )
    repo_expr = "${{ github.repository }}"

    evaluation_script = _build_evaluation_script(result_specs, render_context)
    indented_script = _indent_script_for_yaml(evaluation_script)

    return (
        'name: "Stagr governance"\n'
        "\n"
        "on:\n"
        "  pull_request_target:\n"
        "    types: [opened, synchronize, reopened, ready_for_review, labeled, unlabeled]\n"
        "  check_suite:\n"
        "    types: [completed]\n"
        "\n"
        "permissions:\n"
        "  pull-requests: read\n"
        "  checks: read\n"
        "\n"
        "concurrency:\n"
        f'  group: "stagr-governance-{pr_number_expr}"\n'
        "  cancel-in-progress: false\n"
        "\n"
        "jobs:\n"
        "  evaluate-signals:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Acquire Stagr App installation token\n"
        "        id: app-token\n"
        f"        uses: {_APP_TOKEN_ACTION_REF}\n"
        "        with:\n"
        f'          app-id: "{publisher_app_id}"\n'
        f'          private-key: "{private_key_expr}"\n'
        "\n"
        "      - name: Evaluate stage result signals\n"
        "        env:\n"
        f'          GH_TOKEN: "{app_token_output_expr}"\n'
        f'          STAGR_APP_ID: "{publisher_app_id}"\n'
        f'          PR_HEAD_SHA: "{pr_head_sha_expr}"\n'
        f'          REPO: "{repo_expr}"\n'
        "        run: |\n"
        f"{indented_script}"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _indent_script_for_yaml(script: str) -> str:
    """Prefix each line of script with the YAML run-block indent.

    Empty lines remain empty (no trailing spaces) to keep YAML valid.
    The result ends with a single newline.
    """
    lines: list[str] = []
    for raw_line in script.splitlines():
        if raw_line.strip():
            lines.append(_YAML_SCRIPT_LINE_INDENT + raw_line)
        else:
            lines.append("")
    return "\n".join(lines) + "\n"


def _build_evaluation_script(
    result_specs: tuple[StageResultSpec, ...],
    render_context: RenderContext,
) -> str:
    """Return the complete shell script body for the evaluate-signals step."""
    stage_call_lines = _build_stage_evaluation_call_lines(result_specs, render_context)

    return (
        _EVALUATE_SIGNAL_FUNCTION_BODY
        + "\n"
        + "overall_pass=true\n"
        + stage_call_lines
        + "\n"
        + 'if [[ "${overall_pass}" == "false" ]]; then\n'
        + "  echo \"::error::One or more blocking stage signals did not pass."
        + " Merge is not eligible.\"\n"
        + "  exit 1\n"
        + "fi\n"
        + 'echo "All blocking stage signals evaluated. Merge is eligible."\n'
    )


def _build_stage_evaluation_call_lines(
    result_specs: tuple[StageResultSpec, ...],
    render_context: RenderContext,
) -> str:
    """Return shell lines that call evaluate_stage_signal for each stage spec.

    Each stage marked as blocking in MergePolicy.blocking_stage_ids is passed
    the 'blocking' gate argument; all other stages receive 'non_blocking'.
    """
    blocking_stage_ids = set(render_context.merge_policy.blocking_stage_ids)
    lines: list[str] = []
    for spec in result_specs:
        gate_argument = "blocking" if spec.stage_id in blocking_stage_ids else "non_blocking"
        lines.append(
            f'evaluate_stage_signal'
            f' "{spec.stage_id}"'
            f' "{spec.signal_selector}"'
            f' "{gate_argument}"'
            f" || overall_pass=false\n"
        )
    return "".join(lines)


# ---------------------------------------------------------------------------
# Embedded shell function definition
# ---------------------------------------------------------------------------

# The evaluate_stage_signal function is a fixed template. It uses shell
# variables REPO, PR_HEAD_SHA, and STAGR_APP_ID (all passed via the env:
# block of the generated step) plus three positional arguments:
#   $1 = stage_id   (for error messages)
#   $2 = signal_selector (Check Run name)
#   $3 = blocking_gate  ("blocking" | "non_blocking")
#
# The expected schemaVersion is hardcoded as "1" (matches
# _EXPECTED_STAGE_RESULT_SIGNAL_SCHEMA_VERSION).

_EVALUATE_SIGNAL_FUNCTION_BODY = """\
set -euo pipefail

evaluate_stage_signal() {
  local stage_id="$1"
  local signal_selector="$2"
  local blocking_gate="$3"

  # Locate the single Check Run for this stage on the current head SHA.
  local check_runs_json
  check_runs_json="$(gh api \\
    "repos/${REPO}/commits/${PR_HEAD_SHA}/check-runs?check_name=${signal_selector}&per_page=10" \\
    --jq '[.check_runs[]]' 2>&1)" || {
    echo "::error::Failed to query Check Runs for stage '${stage_id}'" \\
      "on SHA '${PR_HEAD_SHA}': ${check_runs_json}"
    return 1
  }

  local check_run_count
  check_run_count="$(echo "${check_runs_json}" | jq 'length')"

  # Fail closed: no Check Run found.
  if [[ "${check_run_count}" -eq 0 ]]; then
    echo "::error::No Check Run found for stage '${stage_id}'" \\
      "(selector: '${signal_selector}') on SHA '${PR_HEAD_SHA}'." \\
      "Merge blocked until the stage has run."
    return 1
  fi

  # Fail closed: duplicate Check Runs — never silently resolve ambiguity.
  if [[ "${check_run_count}" -gt 1 ]]; then
    echo "::error::Duplicate Check Runs found for stage '${stage_id}'" \\
      "on SHA '${PR_HEAD_SHA}': ${check_run_count} found, expected exactly 1." \\
      "Merge blocked — duplicates must be resolved explicitly."
    return 1
  fi

  local check_run
  check_run="$(echo "${check_runs_json}" | jq '.[0]')"

  # Publisher identity verification: only trust Check Runs from the Stagr App.
  local publisher_app_id
  publisher_app_id="$(echo "${check_run}" | jq -r '.app.id | tostring')"
  if [[ "${publisher_app_id}" != "${STAGR_APP_ID}" ]]; then
    echo "::error::Publisher identity mismatch for stage '${stage_id}':" \\
      "expected Stagr App ID '${STAGR_APP_ID}', found '${publisher_app_id}'." \\
      "Rejecting signal — Check Run not published by the trusted Stagr App."
    return 1
  fi

  # Signal deserialization: read from output.summary JSON, not native fields.
  local summary_json
  summary_json="$(echo "${check_run}" | jq -r '.output.summary // ""')"
  if [[ -z "${summary_json}" ]]; then
    echo "::error::Check Run for stage '${stage_id}' has no output.summary payload." \\
      "Cannot deserialize StageResultSignal."
    return 1
  fi

  # Validate schemaVersion before deserializing any other fields.
  local schema_version
  schema_version="$(echo "${summary_json}" | jq -r '.schemaVersion // ""' 2>/dev/null || echo "")"
  if [[ "${schema_version}" != "1" ]]; then
    echo "::error::Unsupported schemaVersion '${schema_version}' for stage '${stage_id}'." \\
      "Expected '1'. Cannot safely deserialize StageResultSignal."
    return 1
  fi

  # Deserialize StageResultSignal fields from the validated payload.
  local signal_head_sha signal_state signal_conclusion
  signal_head_sha="$(echo "${summary_json}" | jq -r '.headSha // ""')"
  signal_state="$(echo "${summary_json}" | jq -r '.state // ""')"
  signal_conclusion="$(echo "${summary_json}" | jq -r '.conclusion // ""')"

  # Head SHA binding: ignore stale signals bound to a prior commit.
  if [[ "${signal_head_sha}" != "${PR_HEAD_SHA}" ]]; then
    echo "::warning::Stale StageResultSignal for stage '${stage_id}':" \\
      "signal bound to '${signal_head_sha}', current head is '${PR_HEAD_SHA}'." \\
      "Ignoring signal for prior commit."
    return 1
  fi

  # State check: stage must be COMPLETED before the conclusion is meaningful.
  if [[ "${signal_state}" != "completed" ]]; then
    echo "::warning::Stage '${stage_id}' has not completed (state: '${signal_state}')." \\
      "Waiting for stage completion before evaluating conclusion."
    return 1
  fi

  # Conclusion evaluation — PASS is the only merge-eligible outcome.
  if [[ "${signal_conclusion}" == "pass" ]]; then
    echo "Stage '${stage_id}': PASS (eligible for merge)"
    return 0
  fi

  # Non-blocking stages are informational; their conclusions do not block merge.
  if [[ "${blocking_gate}" != "blocking" ]]; then
    echo "Stage '${stage_id}': conclusion '${signal_conclusion}' (non-blocking — informational only)"
    return 0
  fi

  # Blocking stage: BLOCKED and FAILED have distinct, actionable messages.
  if [[ "${signal_conclusion}" == "blocked" ]]; then
    echo "::error::Stage '${stage_id}' is BLOCKED:" \\
      "findings must be resolved before merge is allowed."
    return 1
  elif [[ "${signal_conclusion}" == "failed" ]]; then
    echo "::error::Stage '${stage_id}' FAILED:" \\
      "stage did not complete due to an infrastructure failure." \\
      "Retry the stage workflow to unblock."
    return 1
  else
    echo "::error::Stage '${stage_id}' has unrecognised conclusion '${signal_conclusion}'." \\
      "Merge blocked."
    return 1
  fi
}
"""
