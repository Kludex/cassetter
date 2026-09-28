from __future__ import annotations

from collections.abc import Iterable

from cassetter.cassette import BeforeRecordRequest, RawRequest, SkipRecording


def extract_headers(items: Iterable[tuple[str | bytes, str | bytes]] | None) -> dict[str, list[str]]:
    """Group header pairs by lowercased name, decoding names and values that arrive as bytes.

    HTTP headers are latin-1 on the wire, and clients such as botocore hand
    them to urllib3 as bytes, which `str()` would render as `"b'...'"`.
    """
    result: dict[str, list[str]] = {}
    if items is None:
        return result
    for key, value in items:
        name = key.decode("latin-1") if isinstance(key, bytes) else str(key)
        text = value.decode("latin-1") if isinstance(value, bytes) else str(value)
        result.setdefault(name.lower(), []).append(text)
    return result


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
