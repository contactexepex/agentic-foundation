"""Routing workflow YAML generator for the GitHub platform renderer.

Generates the Phase 2a routing artifact: a GitHub Actions workflow that classifies
each PR head commit as FAST or NORMAL based on the RoutingPolicy.fast_path settings
and publishes the result as a ``RouteClassification`` Check Run authenticated by the
Stagr GitHub App.

Security invariant: the workflow uses ``pull_request_target`` so the trusted
base-branch workflow definition is used. No PR head content is checked out or
executed. The App installation token acquired in the first step is the only
credential; the GITHUB_TOKEN is not used for the Check Run signal (which must
carry the App identity for provenance verification).

Token isolation: ``GH_TOKEN`` is set to the App installation token only for the
Check Run publication step. The ``changed-files`` fetch step also uses the App
token so it can read private repositories, but it performs only a read-only API
call. The App token is never written to GITHUB_OUTPUT or any artifact.
"""
from __future__ import annotations

import base64
import json

from stagr.core.models import FastPathPolicy

# Stable Check Run name emitted by the routing artifact and consumed by the
# governance artifact. This string is rendered as a literal into both artifacts;
# changing it is a breaking change that requires coordinated governance updates.
ROUTE_CLASSIFICATION_CHECK_RUN_NAME = "stagr/route-classification"

# Output file name, relative to the ``output_dir/.github/workflows/`` directory.
ROUTING_WORKFLOW_FILENAME = "routing.yml"

# Pinned commit SHA for actions/create-github-app-token v1.11.1.
# Immutable pinning is required per AGENTS.md supply-chain integrity requirement.
_APP_TOKEN_ACTION_REF = (
    "actions/create-github-app-token@a6de09a5e3e8eb40028eda38d7ad96aea41ac75e"
    "  # v1.11.1"
)


def classify_route_from_changed_files(
    changed_file_paths: list[str],
    fast_path_patterns: list[str],
) -> str:
    """Classify a PR as FAST or NORMAL given its changed file paths and patterns.

    Returns ``'FAST'`` when ALL changed file paths match at least one pattern and
    the file list is non-empty. Returns ``'NORMAL'`` when any file does not match
    any pattern, or when the changed file list is empty.

    Pattern matching uses ``fnmatch.fnmatch`` semantics, where ``*`` matches any
    characters including ``/`` (i.e., any subpath) and ``**`` is treated the same
    as ``*``. This mirrors the behaviour embedded in the generated workflow step.

    Args:
        changed_file_paths: List of relative file paths changed by the PR.
        fast_path_patterns: Glob patterns from RoutingPolicy.fast_path.match.paths.

    Returns:
        ``'FAST'`` if all paths match any pattern and the list is non-empty;
        ``'NORMAL'`` otherwise.
    """
    import fnmatch

    if not changed_file_paths:
        return "NORMAL"

    def matches_any_pattern(file_path: str) -> bool:
        return any(fnmatch.fnmatch(file_path, pattern) for pattern in fast_path_patterns)

    return "FAST" if all(matches_any_pattern(fp) for fp in changed_file_paths) else "NORMAL"


def generate_routing_workflow_yaml(
    fast_path_policy: FastPathPolicy | None,
    publisher_app_id: str,
    publisher_private_key_secret: str,
) -> str:
    """Generate the complete routing workflow YAML string.

    When ``fast_path_policy`` is ``None`` (fast path disabled), the generated
    workflow immediately emits ``RouteClassification=NORMAL`` with no path analysis.
    The workflow has exactly two steps: token acquisition and Check Run publication.

    When ``fast_path_policy`` is set, the generated workflow has four steps:
    token acquisition, changed-file path retrieval, route classification, and
    Check Run publication. The ``fast_path_policy.match.paths`` patterns are
    embedded as a JSON literal in the classify step.

    Args:
        fast_path_policy: Routing policy; ``None`` means fast path is disabled.
        publisher_app_id: Stagr GitHub App numeric ID, rendered as a literal.
        publisher_private_key_secret: Repository secret name holding the App's
            RSA private key, referenced as ``${{ secrets.<name> }}``.

    Returns:
        Complete GitHub Actions workflow YAML as a string.
    """
    private_key_secret_expr = f"${{{{ secrets.{publisher_private_key_secret} }}}}"
    app_token_output_expr = "${{ steps.app-token.outputs.token }}"

    token_acquisition_step = _build_token_acquisition_step(
        publisher_app_id, private_key_secret_expr
    )

    if fast_path_policy is None:
        payload_steps = _build_normal_only_publication_step(app_token_output_expr)
    else:
        payload_steps = _build_path_analysis_steps(fast_path_policy, app_token_output_expr)

    return (
        f'name: "Stagr route classification"\n'
        f"\n"
        f"on:\n"
        f"  pull_request_target:\n"
        f"    types: [opened, reopened, synchronize, ready_for_review, edited]\n"
        f"\n"
        f"concurrency:\n"
        f'  group: "stagr-routing-${{{{ github.event.pull_request.number }}}}${{{{ (github.event.action == \'edited\' && github.event.changes.base == \'\') && \'-noop\' || \'\' }}}}"\n'
        f"  cancel-in-progress: true\n"
        f"\n"
        f"jobs:\n"
        f"  classify:\n"
        f"    runs-on: ubuntu-latest\n"
        f"    if: github.event_name != 'pull_request_target' || github.event.action != 'edited' || github.event.changes.base != ''\n"
        f"    permissions:\n"
        f"      pull-requests: read\n"
        f"      contents: read\n"
        f"    steps:\n"
        f"{token_acquisition_step}"
        f"\n"
        f"{payload_steps}"
    )


def _build_token_acquisition_step(
    publisher_app_id: str,
    private_key_secret_expr: str,
) -> str:
    """Return the YAML block for the App installation token acquisition step.

    This is the first step in every routing workflow variant. The produced token
    is referenced as ``${{ steps.app-token.outputs.token }}`` in later steps.
    """
    return (
        f"      - name: Acquire Stagr App installation token\n"
        f"        id: app-token\n"
        f"        uses: {_APP_TOKEN_ACTION_REF}\n"
        f"        with:\n"
        f'          app-id: "{publisher_app_id}"\n'
        f'          private-key: "{private_key_secret_expr}"\n'
    )


def _build_normal_only_publication_step(app_token_output_expr: str) -> str:
    """Return the YAML block for the NORMAL-only Check Run publication step.

    Used when fast_path is disabled. Emits ``RouteClassification=NORMAL``
    immediately without any path analysis. No ``changed-files`` or classify
    step is present.
    """
    return (
        f"      - name: Publish RouteClassification Check Run (NORMAL — fast path disabled)\n"
        f"        env:\n"
        f'          GH_TOKEN: "{app_token_output_expr}"\n'
        f'          HEAD_SHA: "${{{{ github.event.pull_request.head.sha }}}}"\n'
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f"          gh api --method POST \\\n"
        f'            "repos/${{GITHUB_REPOSITORY}}/check-runs" \\\n'
        f'            -f name="{ROUTE_CLASSIFICATION_CHECK_RUN_NAME}" \\\n'
        f'            -f head_sha="${{HEAD_SHA}}" \\\n'
        f"            -f status=completed \\\n"
        f"            -f conclusion=success \\\n"
        f'            -f output[title]="RouteClassification=NORMAL" \\\n'
        f'            -f output[summary]="Fast path is disabled; all PRs are routed to the NORMAL lane."\n'
    )


def _build_path_analysis_steps(
    fast_path_policy: FastPathPolicy,
    app_token_output_expr: str,
) -> str:
    """Return YAML blocks for the three steps that retrieve, classify, and publish.

    Used when fast_path is configured. Embeds the fast_path.match.paths patterns
    as a JSON literal constant in the classify step so path classification is
    deterministic and requires no external API calls beyond the changed-files fetch.
    """
    patterns_json = json.dumps(list(fast_path_policy.match.paths))

    changed_files_step = _build_changed_files_step(app_token_output_expr)
    classify_step = _build_classify_step(patterns_json)
    publication_step = _build_full_publication_step(app_token_output_expr)

    return f"{changed_files_step}\n{classify_step}\n{publication_step}"


def _build_changed_files_step(app_token_output_expr: str) -> str:
    """Return the YAML block for the step that fetches changed file paths from GitHub."""
    return (
        f"      - name: Get changed file paths\n"
        f"        id: changed-files\n"
        f"        env:\n"
        f'          GH_TOKEN: "{app_token_output_expr}"\n'
        f'          PR_NUMBER: "${{{{ github.event.pull_request.number }}}}"\n'
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f"          pr_meta=$(gh api \"repos/${{GITHUB_REPOSITORY}}/pulls/${{PR_NUMBER}}\" --jq '.changed_files')\n"
        f'          echo "changed_files_count=${{pr_meta}}" >> "$GITHUB_OUTPUT"\n'
        f"          raw_files=$(gh api \"repos/${{GITHUB_REPOSITORY}}/pulls/${{PR_NUMBER}}/files\" \\\n"
        f"            --paginate --slurp)\n"
        f"          api_record_count=$(echo \"${{raw_files}}\" | jq '[.[][]] | length')\n"
        f'          echo "api_record_count=${{api_record_count}}" >> "$GITHUB_OUTPUT"\n'
        f"          files_json=$(echo \"${{raw_files}}\" | jq -c '[.[][] | .filename, (.previous_filename // empty)] | unique')\n"
        f'          echo "files_json=${{files_json}}" >> "$GITHUB_OUTPUT"\n'
    )


def _build_classify_step(patterns_json: str) -> str:
    """Return the YAML block for the step that classifies the route from changed files.

    Embeds the fast_path patterns as a base64-encoded constant and runs inline Python
    to classify the route. Base64 encoding is used so that glob patterns containing
    apostrophes (e.g. ``docs/o'hare/**``) cannot break YAML single-quoted scalar syntax.
    Using ``fnmatch.fnmatch``, which treats ``*`` and ``**`` as matching any characters
    including path separators, implements the same semantics as
    ``classify_route_from_changed_files``.
    """
    patterns_b64 = base64.b64encode(patterns_json.encode()).decode()
    return (
        f"      - name: Classify route\n"
        f"        id: classify\n"
        f"        env:\n"
        f'          FILES_JSON: "${{{{ steps.changed-files.outputs.files_json }}}}"\n'
        f'          CHANGED_FILES_COUNT: "${{{{ steps.changed-files.outputs.changed_files_count }}}}"\n'
        f'          API_RECORD_COUNT: "${{{{ steps.changed-files.outputs.api_record_count }}}}"\n'
        f"          FAST_PATH_PATTERNS_B64: '{patterns_b64}'\n"
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f"          python3 - <<'PYEOF'\n"
        f"          import base64, fnmatch, json, os\n"
        f"          files = json.loads(os.environ['FILES_JSON'])\n"
        f"          changed_files_count = int(os.environ['CHANGED_FILES_COUNT'])\n"
        f"          api_record_count = int(os.environ['API_RECORD_COUNT'])\n"
        f"          patterns = json.loads(base64.b64decode(os.environ['FAST_PATH_PATTERNS_B64']).decode())\n"
        f"          if api_record_count < changed_files_count:\n"
        f"              route = 'NORMAL'\n"
        f"          else:\n"
        f"              def matches_any_pattern(file_path):\n"
        f"                  return any(fnmatch.fnmatch(file_path, pat) for pat in patterns)\n"
        f"              is_fast = bool(files) and all(matches_any_pattern(fp) for fp in files)\n"
        f"              route = 'FAST' if is_fast else 'NORMAL'\n"
        f"          with open(os.environ['GITHUB_OUTPUT'], 'a') as out:\n"
        f"              out.write('route=' + route + '\\n')\n"
        f"          PYEOF\n"
    )


def _build_full_publication_step(app_token_output_expr: str) -> str:
    """Return the YAML block for the Check Run publication step (FAST or NORMAL)."""
    return (
        f"      - name: Publish RouteClassification Check Run\n"
        f"        env:\n"
        f'          GH_TOKEN: "{app_token_output_expr}"\n'
        f'          HEAD_SHA: "${{{{ github.event.pull_request.head.sha }}}}"\n'
        f'          ROUTE: "${{{{ steps.classify.outputs.route }}}}"\n'
        f"        run: |\n"
        f"          set -euo pipefail\n"
        f"          gh api --method POST \\\n"
        f'            "repos/${{GITHUB_REPOSITORY}}/check-runs" \\\n'
        f'            -f name="{ROUTE_CLASSIFICATION_CHECK_RUN_NAME}" \\\n'
        f'            -f head_sha="${{HEAD_SHA}}" \\\n'
        f"            -f status=completed \\\n"
        f"            -f conclusion=success \\\n"
        f'            -f output[title]="RouteClassification=${{ROUTE}}" \\\n'
        f'            -f output[summary]="PR classified as ${{ROUTE}} route."\n'
    )
