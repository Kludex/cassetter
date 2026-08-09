from __future__ import annotations

from cassetter.cassette import (
    BeforeRecordRequest,
    RawRequest,
    SkipRecording,
    body_to_bytes as body_to_bytes,
)


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
