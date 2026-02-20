from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import aiohttp
import aiohttp.client_reqrep
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from vcr_but_better.cassette import Cassette, NoMatchError


class AiohttpInterceptor:
    """Intercepts aiohttp requests by patching ClientSession._request."""

    def __init__(self) -> None:
        self._cassette: Cassette | None = None
        self._patcher: Any = None

    def install(self, cassette: Cassette) -> None:
        self._cassette = cassette
        original_request = aiohttp.ClientSession._request

        interceptor = self

        async def patched_request(
            session: aiohttp.ClientSession,
            method: str,
            str_or_url: str | URL,
            **kwargs: Any,
        ) -> aiohttp.ClientResponse:
            assert interceptor._cassette is not None
            uri = str(URL(str_or_url))
            headers = _extract_request_headers(kwargs.get("headers"))
            body = _extract_request_body(kwargs)

            try:
                response = interceptor._cassette.play(method.upper(), uri, headers, body)
                return _build_aiohttp_response(method, uri, response)
            except NoMatchError:
                if not interceptor._cassette.can_record:
                    raise

            real_response = await original_request(session, method, str_or_url, **kwargs)
            resp_body = await real_response.read()
            resp_headers = _extract_response_headers(real_response.headers)

            interceptor._cassette.record(
                method=method.upper(),
                uri=uri,
                request_headers=headers,
                request_body=body,
                status=real_response.status,
                response_headers=resp_headers,
                response_body=resp_body,
            )
            return real_response

        self._patcher = patch.object(aiohttp.ClientSession, "_request", patched_request)
        self._patcher.start()

    def uninstall(self) -> None:
        if self._patcher is not None:
            self._patcher.stop()
            self._patcher = None
        self._cassette = None


def _extract_request_headers(headers: Any) -> dict[str, list[str]]:
    if headers is None:
        return {}
    result: dict[str, list[str]] = {}
    if isinstance(headers, dict):
        for k, v in headers.items():
            result.setdefault(str(k).lower(), []).append(str(v))
    else:
        for k, v in headers.items():
            result.setdefault(str(k).lower(), []).append(str(v))
    return result


def _extract_request_body(kwargs: dict[str, Any]) -> bytes | None:
    if "data" in kwargs and kwargs["data"] is not None:
        data = kwargs["data"]
        if isinstance(data, bytes):
            return data
        if isinstance(data, str):
            return data.encode()
    if "json" in kwargs and kwargs["json"] is not None:
        return json.dumps(kwargs["json"]).encode()
    return None


def _extract_response_headers(headers: CIMultiDictProxy[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in headers.items():
        result.setdefault(key.lower(), []).append(value)
    return result


def _build_aiohttp_response(method: str, uri: str, response: object) -> aiohttp.ClientResponse:
    from vcr_but_better._core import HttpResponse as _HttpResponse

    assert isinstance(response, _HttpResponse)

    body = response.body
    if body.body_type == "json":
        content = json.dumps(body.content).encode()
    elif body.body_type == "text":
        content = body.content.encode() if isinstance(body.content, str) else b""
    elif body.body_type == "binary":
        content = body.content if isinstance(body.content, bytes) else b""
    else:
        content = b""

    headers_multi: CIMultiDict[str] = CIMultiDict()
    for key, values in response.headers.items():
        for v in values:
            headers_multi.add(key, v)

    # Build a mock-like response
    resp = aiohttp.ClientResponse(
        method=method,
        url=URL(uri),
        writer=None,  # type: ignore[arg-type]
        continue100=None,
        timer=None,  # type: ignore[arg-type]
        request_info=aiohttp.RequestInfo(
            url=URL(uri),
            method=method,
            headers=CIMultiDictProxy(CIMultiDict()),
            real_url=URL(uri),
        ),
        traces=[],
        loop=None,  # type: ignore[arg-type]
        session=None,  # type: ignore[arg-type]
    )
    resp.status = response.status
    resp._headers = CIMultiDictProxy(headers_multi)  # type: ignore[assignment]
    resp._body = content  # type: ignore[assignment]
    return resp
