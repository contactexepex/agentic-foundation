"""GateDispositionSpec evaluation: given completion, is the result PASS or BLOCKED?"""
from __future__ import annotations

from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    OLD_HEAD_SHA,
    PULL_NUMBER,
    always_pass_gate,
    build_config,
    build_review_thread,
    build_world,
    no_open_threads_gate,
)
from neutral_core_tests.stage_signal_tests.fake_github import REPOSITORY, FakeGitHubApi
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


def _evaluate(fake: FakeGitHubApi, gate: dict, evidence_bodies: tuple = ()) -> str:
    owner, _, name = REPOSITORY.partition("/")
    rule = build_config(gate=gate).gate_rule
    return runtime.GateEvaluator(rule, fake, owner, name).evaluate(PULL_NUMBER, HEAD_SHA, evidence_bodies)


def test_always_pass_passes_without_calling_github() -> None:
    fake = build_world()
    fake.failing_path_fragments.add("graphql")
    assert _evaluate(fake, always_pass_gate()) == "pass"


def test_explicit_pass_marker_present_in_evidence_passes() -> None:
    gate = {"kind": "explicit_pass_marker", "selector": "stagr:pass:review",
            "createdBy": "", "headShaBound": False}
    assert _evaluate(build_world(), gate, ("done\nstagr:pass:review",)) == "pass"


def test_explicit_pass_marker_absent_from_evidence_blocks() -> None:
    gate = {"kind": "explicit_pass_marker", "selector": "stagr:pass:review",
            "createdBy": "", "headShaBound": False}
    assert _evaluate(build_world(), gate, ("done",)) == "blocked"


def test_zero_threads_passes() -> None:
    assert _evaluate(build_world(), no_open_threads_gate()) == "pass"


def test_open_thread_blocks() -> None:
    assert _evaluate(build_world(threads=[build_review_thread()]), no_open_threads_gate()) == "blocked"


def test_resolved_thread_does_not_block() -> None:
    fake = build_world(threads=[build_review_thread(is_resolved=True)])
    assert _evaluate(fake, no_open_threads_gate()) == "pass"


def test_thread_by_another_author_does_not_block() -> None:
    human = build_review_thread(author_login="alice", author_type="User")
    assert _evaluate(build_world(threads=[human]), no_open_threads_gate()) == "pass"


def test_bot_thread_is_matched_although_graphql_omits_the_bot_suffix() -> None:
    """Regression guard: GraphQL logs the Codex bot as 'chatgpt-codex-connector' (no [bot])."""
    fake = build_world(threads=[build_review_thread(author_login="chatgpt-codex-connector")])
    assert _evaluate(fake, no_open_threads_gate()) == "blocked"


def test_human_named_like_the_bot_does_not_block() -> None:
    lookalike = build_review_thread(author_login="chatgpt-codex-connector", author_type="User")
    assert _evaluate(build_world(threads=[lookalike]), no_open_threads_gate()) == "pass"


def test_head_bound_scope_ignores_threads_from_an_older_review_commit() -> None:
    fake = build_world(threads=[build_review_thread(review_commit=OLD_HEAD_SHA)])
    assert _evaluate(fake, no_open_threads_gate(head_sha_bound=True)) == "pass"


def test_head_bound_scope_counts_threads_from_the_current_review_commit() -> None:
    fake = build_world(threads=[build_review_thread(review_commit=HEAD_SHA.upper())])
    assert _evaluate(fake, no_open_threads_gate(head_sha_bound=True)) == "blocked"


def test_head_bound_scope_fails_closed_when_the_review_commit_is_unknown() -> None:
    fake = build_world(threads=[build_review_thread(review_commit=None)])
    assert _evaluate(fake, no_open_threads_gate(head_sha_bound=True)) == "blocked"


def test_unbound_scope_counts_threads_from_any_review_commit() -> None:
    fake = build_world(threads=[build_review_thread(review_commit=OLD_HEAD_SHA)])
    assert _evaluate(fake, no_open_threads_gate(head_sha_bound=False)) == "blocked"


def test_open_thread_on_a_later_graphql_page_is_found() -> None:
    threads = [build_review_thread(is_resolved=True) for _ in range(250)] + [build_review_thread()]
    fake = build_world(threads=threads)
    fake.graphql_page_size = 100
    assert _evaluate(fake, no_open_threads_gate()) == "blocked"
