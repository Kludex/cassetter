from __future__ import annotations

import difflib
import fnmatch
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cassetter._core import HttpResponse


class ResponseMismatchError(AssertionError):
    """Raised in `verify` mode when a live response differs from its recording."""


@dataclass(frozen=True, kw_only=True, slots=True)
class Compare:
    """What `verify` mode compares between a recorded response and the live one.

    The status is always compared. Everything not listed here is ignored.

    Args:
        headers: Response header names to compare by value. Globs such as `x-price-*` are allowed.
        json_ignore: Paths removed from JSON bodies before comparing, in the `ignore_json_paths` syntax
            (`id`, `data.created`, `items[0].id`). With `sse`, they apply to each event's payload.
        sse: Compare the body as a list of Server-Sent Events `data:` payloads, so chunk boundaries do not matter.
        float_tolerance: Largest absolute difference between two JSON numbers that still counts as equal.
    """

    headers: list[str] = field(default_factory=list)
    json_ignore: list[str] = field(default_factory=list)
    sse: bool = False
    float_tolerance: float = 0.0


BeforeCompareResponse = Callable[[HttpResponse, HttpResponse], tuple[HttpResponse, HttpResponse]]
"""Receives `(recorded, live)` and returns them normalized, for differences `Compare` cannot express."""


def compare_responses(compare: Compare, recorded: HttpResponse, live: HttpResponse, label: str) -> None:
    """Raise `ResponseMismatchError` with a unified diff when `live` is not equivalent to `recorded`."""
    expected = _render(_normalize(compare, recorded))
    actual = _render(_tolerate(_normalize(compare, recorded), _normalize(compare, live), compare.float_tolerance))
    if expected == actual:
        return
    diff = difflib.unified_diff(expected, actual, "recorded", "live", lineterm="")
    raise ResponseMismatchError(f"{label}\n" + "\n".join(diff))


def _normalize(compare: Compare, response: HttpResponse) -> dict[str, Any]:
    headers = {
        name: values
        for name, values in sorted(response.headers.items())
        if any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in compare.headers)
    }
    return {"status": response.status, "headers": headers, "body": _body(compare, response)}


def _body(compare: Compare, response: HttpResponse) -> Any:
    body = response.body
    content = body.content
    if body.body_type == "json":
        return _drop_paths(content, compare.json_ignore, "")
    if compare.sse and isinstance(content, str):
        return [_drop_paths(event, compare.json_ignore, "") for event in _sse_events(content)]
    return content


def _sse_events(text: str) -> list[Any]:
    events: list[Any] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        lines = [line[5:].removeprefix(" ") for line in block.split("\n") if line.startswith("data:")]
        if not lines:
            continue
        data = "\n".join(lines)
        try:
            events.append(json.loads(data))
        except json.JSONDecodeError:
            events.append(data)
    return events


def _drop_paths(value: Any, paths: list[str], current: str) -> Any:
    if isinstance(value, dict):
        prefix = f"{current}." if current else ""
        return {key: _drop_paths(item, paths, prefix + key) for key, item in value.items() if prefix + key not in paths}
    if isinstance(value, list):
        return [_drop_paths(item, paths, f"{current}[{i}]") for i, item in enumerate(value)]
    return value


def _tolerate(recorded: Any, live: Any, tolerance: float) -> Any:
    """`live` with numbers within `tolerance` of their recording replaced by it, so they drop out of the diff."""
    if isinstance(recorded, dict) and isinstance(live, dict):
        return {
            key: _tolerate(recorded[key], value, tolerance) if key in recorded else value for key, value in live.items()
        }
    if isinstance(recorded, list) and isinstance(live, list):
        return [_tolerate(r, v, tolerance) for r, v in zip(recorded, live)] + live[len(recorded) :]
    if _is_number(recorded) and _is_number(live) and abs(recorded - live) <= tolerance:
        return recorded
    return live


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _render(normalized: dict[str, Any]) -> list[str]:
    lines = [f"status: {normalized['status']}", "@@ headers @@"]
    lines += [f"{name}: {value}" for name, values in normalized["headers"].items() for value in values]
    lines.append("@@ body @@")
    body = normalized["body"]
    if isinstance(body, bytes):
        lines.append(repr(body))
    elif isinstance(body, str):
        lines += body.splitlines()
    else:
        lines += json.dumps(body, indent=2, sort_keys=True).splitlines()
    return lines
