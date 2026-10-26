from __future__ import annotations

import difflib
import fnmatch
import json
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from cassetter._core import Body, GrpcResponse, HttpRequest, HttpResponse, WsFrame


class ResponseMismatchError(AssertionError):
    """Raised in `verify` mode when a live response or observed request differs from its recording."""


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
        decode: Turns a body into a JSON-able value before comparing, e.g. OTLP protobuf into spans.
            `json_ignore` and `float_tolerance` apply to what it returns.
    """

    headers: list[str] = field(default_factory=list)
    json_ignore: list[str] = field(default_factory=list)
    sse: bool = False
    float_tolerance: float = 0.0
    decode: Callable[[bytes], Any] | None = None


BeforeCompareResponse = Callable[[HttpResponse, HttpResponse], tuple[HttpResponse, HttpResponse]]
"""Receives `(recorded, live)` and returns them normalized, for differences `Compare` cannot express."""


def compare_responses(compare: Compare, recorded: HttpResponse, live: HttpResponse, label: str) -> None:
    """Raise `ResponseMismatchError` with a unified diff when `live` is not equivalent to `recorded`."""
    _compare(
        compare,
        _normalize(compare, f"status: {recorded.status}", recorded.headers, recorded.body),
        _normalize(compare, f"status: {live.status}", live.headers, live.body),
        label,
    )


def compare_grpc_responses(
    compare: Compare,
    recorded: GrpcResponse,
    live: GrpcResponse,
    messages: Callable[[GrpcResponse], list[Any]],
    label: str,
) -> None:
    """Like `compare_responses`, for the status and the messages `messages` decodes from each body."""
    expected = _grpc(compare, recorded, messages)
    actual = _tolerate(expected, _grpc(compare, live, messages), compare.float_tolerance)
    _diff(_render_sections(expected), _render_sections(actual), label)


def compare_ws_frames(compare: Compare, recorded: list[WsFrame], live: list[WsFrame], label: str) -> None:
    """Like `compare_responses`, for the frames received in order. Sent frames are ignored."""
    expected = _received(compare, recorded)
    actual = _tolerate(expected, _received(compare, live), compare.float_tolerance)
    _diff(_render_sections(expected), _render_sections(actual), label)


def compare_requests(compare: Compare, recorded: HttpRequest, live: HttpRequest, label: str) -> None:
    """Like `compare_responses`, for observed requests. Only the path and query of the URI count."""
    _compare(
        compare,
        _normalize(compare, f"{recorded.method} {_path(recorded.uri)}", recorded.headers, recorded.body),
        _normalize(compare, f"{live.method} {_path(live.uri)}", live.headers, live.body),
        label,
    )


def body_to_bytes(body: Body) -> bytes:
    """Serialize a recorded body to the wire bytes of a replayed response.

    A JSON body is stored parsed, so the original bytes are gone by the time
    this runs: the output is stdlib `json.dumps` formatting, not a byte-for-byte
    reproduction of what the server sent. Callers that recompute Content-Length
    must do so from these bytes.

    `body.content` materializes a fresh Python object on every read, so each
    branch reads it once.
    """
    content = body.content
    if body.body_type == "json":
        return json.dumps(content).encode()
    if body.body_type == "text":
        return content.encode() if isinstance(content, str) else b""
    if body.body_type == "binary":
        return content if isinstance(content, bytes) else b""
    return b""


def _compare(compare: Compare, expected: dict[str, Any], actual: dict[str, Any], label: str) -> None:
    actual["body"]["content"] = _tolerate(
        expected["body"]["content"], actual["body"]["content"], compare.float_tolerance
    )
    _diff(_render(expected), _render(actual), label)


def _diff(expected: list[str], actual: list[str], label: str) -> None:
    if expected == actual:
        return
    diff = difflib.unified_diff(expected, actual, "recorded", "live", lineterm="")
    raise ResponseMismatchError(f"{label}\n" + "\n".join(diff))


def _path(uri: str) -> str:
    # The receiver usually listens on a random port, so the host never matches across runs.
    return urlsplit(uri)._replace(scheme="", netloc="").geturl()


def _normalize(compare: Compare, head: str, headers: dict[str, list[str]], body: Body) -> dict[str, Any]:
    kept: dict[str, list[str]] = {}
    for name, values in sorted(headers.items(), key=lambda item: item[0].lower()):
        if any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in compare.headers):
            kept.setdefault(name.lower(), []).extend(values)
    body_type = "decoded" if compare.decode is not None else body.body_type
    return {"head": head, "headers": kept, "body": {"type": body_type, "content": _body(compare, body)}}


def _body(compare: Compare, body: Body) -> Any:
    if compare.decode is not None:
        return _drop_paths(compare.decode(body_to_bytes(body)), compare.json_ignore, "")
    content = body.content
    if body.body_type == "json":
        return _drop_paths(content, compare.json_ignore, "")
    if compare.sse and isinstance(content, str):
        return [_drop_paths(event, compare.json_ignore, "") for event in _sse_events(content)]
    return content


def _grpc(compare: Compare, response: GrpcResponse, messages: Callable[[GrpcResponse], list[Any]]) -> dict[str, Any]:
    normalized: dict[str, Any] = {"status": f"{response.status_code} {response.status_message}"}
    for i, message in enumerate(messages(response), 1):
        normalized[f"message {i}"] = _drop_paths(message, compare.json_ignore, "")
    return normalized


def _received(compare: Compare, frames: list[WsFrame]) -> dict[str, Any]:
    received = [frame for frame in frames if frame.direction == "recv"]
    return {f"{frame.frame_type} {i}": _frame(compare, frame) for i, frame in enumerate(received, 1)}


def _frame(compare: Compare, frame: WsFrame) -> Any:
    content = frame.body.content
    if frame.frame_type == "close" and isinstance(content, bytes):
        return f"{struct.unpack('>H', content[:2])[0]} {content[2:].decode()}"
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return content
    return _drop_paths(content, compare.json_ignore, "")


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
    if current in paths:
        return None
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
    lines = [normalized["head"], "@@ headers @@"]
    lines += [f"{name}: {value}" for name, values in normalized["headers"].items() for value in values]
    lines.append(f"@@ {normalized['body']['type']} body @@")
    content = normalized["body"]["content"]
    if normalized["body"]["type"] == "json":
        return lines + json.dumps(content, indent=2, sort_keys=True).splitlines()
    return lines + _content_lines(content)


def _render_sections(normalized: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for section, value in normalized.items():
        if isinstance(value, bytes) or (isinstance(value, str) and "\n" not in value):
            lines.append(f"{section}: {value!r}" if isinstance(value, bytes) else f"{section}: {value}")
        else:
            lines += [f"@@ {section} @@", *_content_lines(value)]
    return lines


def _content_lines(content: Any) -> list[str]:
    if isinstance(content, bytes):
        return [repr(content)]
    if isinstance(content, str):
        return content.split("\n")
    return json.dumps(content, indent=2, sort_keys=True).splitlines()
