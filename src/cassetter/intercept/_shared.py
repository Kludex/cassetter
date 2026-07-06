from __future__ import annotations

import json

from cassetter._core import Body
from cassetter.cassette import BeforeRecordRequest, RawRequest, SkipRecording


def apply_before_record_request(
    hook: BeforeRecordRequest | None,
    method: str,
    uri: str,
    headers: dict[str, list[str]],
    body: bytes | None,
) -> RawRequest | None:
    """Run the before_record_request hook.

    Returns the (possibly modified) request, or None if the hook raised
    `SkipRecording` and the caller should pass the request through live.
    """
    request = RawRequest(method, uri, headers, body)
    if hook is None:
        return request
    try:
        return hook(request)
    except SkipRecording:
        return None


def body_to_bytes(body: Body) -> bytes:
    """Serialize a recorded body to the wire bytes of a replayed response.

    JSON bodies are re-serialized with the stdlib `json` module so the output
    matches what was originally recorded (separators and non-ASCII escaping),
    rather than a compact form.
    """
    if body.body_type == "json":
        return json.dumps(body.content).encode()
    if body.body_type == "text":
        return body.content.encode() if isinstance(body.content, str) else b""
    if body.body_type == "binary":
        return body.content if isinstance(body.content, bytes) else b""
    return b""
