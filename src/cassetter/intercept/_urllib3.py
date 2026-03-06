from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import patch

import urllib3
import urllib3.connectionpool
import urllib3.response

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import BypassCassette, NoMatchError, RawRequest


class Urllib3Interceptor:
    """Intercepts HTTP traffic by patching urllib3.HTTPConnectionPool.urlopen."""

    def __init__(self) -> None:
        self._patcher: Any = None

    def install(self) -> None:
        original_urlopen = urllib3.connectionpool.HTTPConnectionPool.urlopen

        def patched_urlopen(
            pool: urllib3.connectionpool.HTTPConnectionPool,
            method: str,
            url: str,
            body: bytes | str | None = None,
            headers: Any = None,
            **kwargs: Any,
        ) -> urllib3.response.HTTPResponse:
            cassette = get_current_cassette()
            if cassette is None:
                return original_urlopen(pool, method, url, body=body, headers=headers, **kwargs)  # type: ignore[return-value]

            full_url = _reconstruct_url(pool, url)

            if cassette.should_bypass(full_url):
                return original_urlopen(pool, method, url, body=body, headers=headers, **kwargs)  # type: ignore[return-value]

            norm_method = method.upper()
            norm_headers = _extract_headers(headers)
            norm_body = body.encode() if isinstance(body, str) else body

            hook = cassette.before_record_request
            if hook is not None:
                try:
                    hook(RawRequest(norm_method, full_url, norm_headers, norm_body))
                except BypassCassette:
                    return original_urlopen(pool, method, url, body=body, headers=headers, **kwargs)  # type: ignore[return-value]

            try:
                response = cassette.play(norm_method, full_url, norm_headers, norm_body)
                return _build_urllib3_response(response, full_url)
            except NoMatchError:
                if not cassette.can_record:
                    raise

            real_response = original_urlopen(pool, method, url, body=body, headers=headers, **kwargs)
            resp_body = real_response.data
            resp_headers = _extract_headers(real_response.headers)

            cassette.record(
                method=norm_method,
                uri=full_url,
                request_headers=norm_headers,
                request_body=norm_body,
                status=real_response.status,
                response_headers=resp_headers,
                response_body=resp_body,
            )

            record_headers = urllib3._collections.HTTPHeaderDict(real_response.headers)
            if "content-length" in record_headers:
                record_headers["content-length"] = str(len(resp_body))

            return urllib3.response.HTTPResponse(
                body=io.BytesIO(resp_body),
                headers=record_headers,
                status=real_response.status,
                preload_content=False,
                decode_content=False,
                request_url=full_url,
            )

        self._patcher = patch.object(urllib3.connectionpool.HTTPConnectionPool, "urlopen", patched_urlopen)
        self._patcher.start()

    def uninstall(self) -> None:
        if self._patcher is not None:
            self._patcher.stop()
            self._patcher = None


def _reconstruct_url(pool: urllib3.connectionpool.HTTPConnectionPool, path: str) -> str:
    scheme = pool.scheme
    host = pool.host
    port = pool.port
    if port and not _is_default_port(scheme, port):
        host_part = f"{host}:{port}"
    else:
        host_part = host
    return f"{scheme}://{host_part}{path}"


def _is_default_port(scheme: str, port: int) -> bool:
    return (scheme == "http" and port == 80) or (scheme == "https" and port == 443)


def _extract_headers(headers: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if headers is None:
        return result
    for key, value in headers.items():
        result.setdefault(str(key).lower(), []).append(str(value))
    return result


def _build_urllib3_response(response: _HttpResponse, request_url: str) -> urllib3.response.HTTPResponse:
    body = response.body
    if body.body_type == "json":
        content = json.dumps(body.content).encode()
    elif body.body_type == "text":
        content = body.content.encode() if isinstance(body.content, str) else b""
    elif body.body_type == "binary":
        content = body.content if isinstance(body.content, bytes) else b""
    else:
        content = b""

    resp_headers = urllib3._collections.HTTPHeaderDict()
    for key, values in response.headers.items():
        for v in values:
            resp_headers.add(key, v)

    if "content-length" in resp_headers:
        resp_headers["content-length"] = str(len(content))

    return urllib3.response.HTTPResponse(
        body=io.BytesIO(content),
        headers=resp_headers,
        status=response.status,
        preload_content=False,
        decode_content=False,
        request_url=request_url,
    )
