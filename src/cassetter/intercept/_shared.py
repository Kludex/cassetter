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
