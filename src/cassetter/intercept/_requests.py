from __future__ import annotations

from typing import Any
from unittest.mock import patch

import requests

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import NoMatchError
from cassetter.intercept._shared import apply_before_record_request, body_to_bytes


class RequestsInterceptor:
    """Intercepts requests by patching Session.send."""

    def __init__(self) -> None:
        self._patcher: Any = None

    def install(self) -> None:
        original_send = requests.Session.send

        def patched_send(
            session: requests.Session, request: requests.PreparedRequest, **kwargs: Any
        ) -> requests.Response:
            cassette = get_current_cassette()
            if cassette is None:  # pragma: no cover - patch active without a cassette context
                return original_send(session, request, **kwargs)

            uri = request.url or ""

            if cassette.should_bypass(uri):
                return original_send(session, request, **kwargs)

            method = (request.method or "GET").upper()
            headers = extract_headers(request.headers)
            raw_body = request.body
            body = raw_body if isinstance(raw_body, bytes) else (raw_body.encode() if raw_body else None)

            raw = apply_before_record_request(cassette.before_record_request, method, uri, headers, body)
            if raw is None:
                return original_send(session, request, **kwargs)
            method, uri, headers, body = raw.method, raw.uri, raw.headers, raw.body

            try:
                response = cassette.play(method, uri, headers, body)
                return build_requests_response(request, response)
            except NoMatchError:
                if not cassette.can_record:
                    raise

            real_response = original_send(session, request, **kwargs)
            # requests exposes the decompressed body via .content, so drop
            # content-encoding to prevent double-decompression when recording
            resp_headers = extract_headers_skip_encoding(real_response.headers)

            cassette.record(
                method=method,
                uri=uri,
                request_headers=headers,
                request_body=body,
                status=real_response.status_code,
                response_headers=resp_headers,
                response_body=real_response.content,
            )
            return real_response

        self._patcher = patch.object(requests.Session, "send", patched_send)
        self._patcher.start()

    def uninstall(self) -> None:
        if self._patcher is not None:
            self._patcher.stop()
            self._patcher = None


def extract_headers(headers: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if headers is None:
        return result
    for key, value in headers.items():
        result.setdefault(str(key).lower(), []).append(str(value))
    return result


def extract_headers_skip_encoding(headers: Any) -> dict[str, list[str]]:
    result = extract_headers(headers)
    result.pop("content-encoding", None)
    return result


def build_requests_response(request: requests.PreparedRequest, response: _HttpResponse) -> requests.Response:

    content = body_to_bytes(response.body)

    resp = requests.Response()
    resp.status_code = response.status
    resp._content = content
    resp.encoding = "utf-8"
    resp.url = request.url or ""
    resp.request = request

    for key, values in response.headers.items():
        for v in values:
            resp.headers[key] = v

    return resp
