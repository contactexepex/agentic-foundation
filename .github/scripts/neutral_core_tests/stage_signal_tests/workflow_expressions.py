"""A small evaluator for the GitHub Actions expressions the stage workflows use, and event payloads.

It supports exactly what the generated ``if:`` conditions and concurrency keys need: property
paths with ``[n]`` indexes (a missing property is null, as in Actions), string/number/boolean/null
literals, ``!``, ``==``, ``!=``, ``&&``, ``||`` and parentheses, with the Actions rules that ``&&``
and ``||`` return an operand (not a boolean), that equality is loose and case-insensitive for
strings, and that ``null``, ``false``, ``0`` and ``''`` are falsy. Anything else raises, so a
future construct cannot be silently mis-evaluated by a test.
"""
from __future__ import annotations

import re
from typing import Any

_TOKEN_PATTERN = re.compile(
    r"\s*(?:(?P<operator>\|\||&&|==|!=|!|\(|\))"
    r"|'(?P<text>(?:[^']|'')*)'"
    r"|(?P<number>-?\d+(?:\.\d+)?)"
    r"|(?P<path>[A-Za-z_][\w-]*(?:\[\d+\])?(?:\.[\w-]+(?:\[\d+\])?)*))"
)
_LITERALS = {"true": True, "false": False, "null": None}


def render_template(template: str, github_context: dict[str, Any]) -> str:
    """Replace every ``${{ expression }}`` of ``template`` with its Actions string form."""
    return re.sub(
        r"\$\{\{(.*?)\}\}",
        lambda match: _to_text(evaluate_expression(match.group(1), github_context)),
        template,
    )


def evaluate_expression(expression: str, github_context: dict[str, Any]) -> Any:
    expression = expression.strip()
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2]
    parser = _Parser(_tokenize(expression), {"github": github_context})
    value = parser.parse_or()
    parser.expect_end()
    return value


def is_truthy(value: Any) -> bool:
    return value not in (None, False, 0, "")


def build_github_context(event_name: str, event: dict[str, Any], run_id: int = 555) -> dict[str, Any]:
    return {"event_name": event_name, "event": event, "run_id": run_id}


def pull_request_event(number: int = 7, head_sha: str = "a" * 40) -> dict[str, Any]:
    return {"pull_request": {"number": number, "head": {"sha": head_sha}}}


def check_run_event(
    name: str, app_id: int, pull_numbers: tuple[int, ...] = (7,), head_sha: str = "a" * 40
) -> dict[str, Any]:
    return {"check_run": {"name": name, "app": {"id": app_id}, "head_sha": head_sha,
                          "pull_requests": [{"number": number} for number in pull_numbers]}}


def check_suite_event(
    app_id: int, pull_numbers: tuple[int, ...] = (7,), head_sha: str = "a" * 40
) -> dict[str, Any]:
    return {"check_suite": {"app": {"id": app_id}, "head_sha": head_sha,
                            "pull_requests": [{"number": number} for number in pull_numbers]}}


def _tokenize(expression: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    while expression[position:].strip():
        match = _TOKEN_PATTERN.match(expression, position)
        if match is None:
            raise ValueError(f"unsupported expression syntax at {expression[position:position + 20]!r}")
        kind = match.lastgroup
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], root: dict[str, Any]) -> None:
        self._tokens, self._index, self._root = tokens, 0, root

    def expect_end(self) -> None:
        if self._index != len(self._tokens):
            raise ValueError(f"unexpected trailing tokens {self._tokens[self._index:]}")

    def parse_or(self) -> Any:
        value = self._parse_and()
        while self._accept("||"):
            right = self._parse_and()
            value = value if is_truthy(value) else right
        return value

    def _parse_and(self) -> Any:
        value = self._parse_equality()
        while self._accept("&&"):
            right = self._parse_equality()
            value = right if is_truthy(value) else value
        return value

    def _parse_equality(self) -> Any:
        value = self._parse_unary()
        while self._peek() in ("==", "!="):
            operator = self._next()[1]
            equal = _loosely_equal(value, self._parse_unary())
            value = equal if operator == "==" else not equal
        return value

    def _parse_unary(self) -> Any:
        if self._accept("!"):
            return not is_truthy(self._parse_unary())
        if self._accept("("):
            value = self.parse_or()
            if not self._accept(")"):
                raise ValueError("missing closing parenthesis")
            return value
        kind, text = self._next()
        if kind == "text":
            return text.replace("''", "'")
        if kind == "number":
            return float(text) if "." in text else int(text)
        if kind == "path":
            return _LITERALS[text] if text in _LITERALS else self._resolve(text)
        raise ValueError(f"unexpected token {text!r}")

    def _resolve(self, path: str) -> Any:
        value: Any = self._root
        for segment in path.split("."):
            name, _, index_text = segment.partition("[")
            value = value.get(name) if isinstance(value, dict) else None
            if index_text:
                position = int(index_text.rstrip("]"))
                value = value[position] if isinstance(value, list) and position < len(value) else None
        return value

    def _peek(self) -> str | None:
        return self._tokens[self._index][1] if self._index < len(self._tokens) else None

    def _next(self) -> tuple[str, str]:
        token = self._tokens[self._index]
        self._index += 1
        return token

    def _accept(self, operator: str) -> bool:
        is_match = self._index < len(self._tokens) and self._tokens[self._index] == ("operator", operator)
        self._index += is_match
        return is_match


def _loosely_equal(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return left.casefold() == right.casefold()
    return _to_number(left) == _to_number(right) if type(left) is not type(right) else left == right


def _to_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        try:
            return float(value) if value.strip() else 0.0
        except ValueError:
            return float("nan")
    return float(value)


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
