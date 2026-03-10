from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import requests
import requests.adapters

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import Cassette, NoMatchError, RawRequest, SkipRecording


class VCRAdapter(requests.adapters.HTTPAdapter):
    """requests HTTPAdapter that records/replays via a Cassette."""

    def __init__(self, cassette: Cassette, real_adapter: requests.adapters.HTTPAdapter) -> None:
        super().__init__()
        self._cassette = cassette
        self._real_adapter = real_adapter

    def send(  # type: ignore[override]
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | None = None,
        verify: bool | str = True,
        cert: str | tuple[str, str] | None = None,
        proxies: dict[str, str] | None = None,
    ) -> requests.Response:
        method = (request.method or "GET").upper()
        uri = request.url or ""
        headers = extract_headers(request.headers)
        body = request.body if isinstance(request.body, bytes) else (request.body.encode() if request.body else None)

        try:
            response = self._cassette.play(method, uri, headers, body)
            return build_requests_response(request, response)
        except NoMatchError:
            if not self._cassette.can_record:
                raise

        real_response = self._real_adapter.send(
            request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies
        )
        resp_headers = extract_headers(real_response.headers)

        self._cassette.record(
            method=method,
            uri=uri,
            request_headers=headers,
            request_body=body,
            status=real_response.status_code,
            response_headers=resp_headers,
            response_body=real_response.content,
        )
        return real_response


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
            if cassette is None:
                return original_send(session, request, **kwargs)

            uri = request.url or ""

            if cassette.should_bypass(uri):
                return original_send(session, request, **kwargs)

            method = (request.method or "GET").upper()
            headers = extract_headers(request.headers)
            raw_body = request.body
            body = raw_body if isinstance(raw_body, bytes) else (raw_body.encode() if raw_body else None)

            hook = cassette.before_record_request
            if hook is not None:
                try:
                    raw = hook(RawRequest(method, uri, headers, body))
                except SkipRecording:
                    return original_send(session, request, **kwargs)
                method, uri, headers, body = raw.method, raw.uri, raw.headers, raw.body

            try:
                response = cassette.play(method, uri, headers, body)
                return build_requests_response(request, response)
            except NoMatchError:
                if not cassette.can_record:
                    raise

            real_response = original_send(session, request, **kwargs)
            resp_headers = extract_headers(real_response.headers)

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


def build_requests_response(request: requests.PreparedRequest, response: _HttpResponse) -> requests.Response:

    body = response.body
    if body.body_type == "json":
        content = json.dumps(body.content).encode()
    elif body.body_type == "text":
        content = body.content.encode() if isinstance(body.content, str) else b""
    elif body.body_type == "binary":
        content = body.content if isinstance(body.content, bytes) else b""
    else:
        content = b""

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
