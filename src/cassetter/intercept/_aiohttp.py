from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import aiohttp
import aiohttp.client_reqrep
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import NoMatchError, RawRequest, SkipRecording


class AiohttpInterceptor:
    """Intercepts aiohttp requests by patching ClientSession._request."""

    def __init__(self) -> None:
        self._patcher: Any = None

    def install(self) -> None:
        original_request = aiohttp.ClientSession._request

        async def patched_request(
            session: aiohttp.ClientSession,
            method: str,
            str_or_url: str | URL,
            **kwargs: Any,
        ) -> aiohttp.ClientResponse:
            cassette = get_current_cassette()
            if cassette is None:
                return await original_request(session, method, str_or_url, **kwargs)

            uri = str(URL(str_or_url))

            if cassette.should_bypass(uri):
                return await original_request(session, method, str_or_url, **kwargs)

            headers = extract_request_headers(kwargs.get("headers"))
            body = extract_request_body(kwargs)

            norm_method = method.upper()

            hook = cassette.before_record_request
            if hook is not None:
                try:
                    raw = hook(RawRequest(norm_method, uri, headers, body))
                except SkipRecording:
                    return await original_request(session, method, str_or_url, **kwargs)
                norm_method, uri, headers, body = raw.method, raw.uri, raw.headers, raw.body

            try:
                response = cassette.play(norm_method, uri, headers, body)
                return build_aiohttp_response(norm_method, uri, response)
            except NoMatchError:
                if not cassette.can_record:
                    raise

            real_response = await original_request(session, method, str_or_url, **kwargs)
            resp_body = await real_response.read()
            resp_headers = extract_response_headers(real_response.headers)

            cassette.record(
                method=norm_method,
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


def extract_request_headers(headers: Any) -> dict[str, list[str]]:
    if headers is None:
        return {}
    result: dict[str, list[str]] = {}
    for k, v in headers.items():
        result.setdefault(str(k).lower(), []).append(str(v))
    return result


def extract_request_body(kwargs: dict[str, Any]) -> bytes | None:
    if "data" in kwargs and kwargs["data"] is not None:
        data = kwargs["data"]
        if isinstance(data, bytes):
            return data
        if isinstance(data, str):
            return data.encode()
    if "json" in kwargs and kwargs["json"] is not None:
        return json.dumps(kwargs["json"]).encode()
    return None


def extract_response_headers(headers: CIMultiDictProxy[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in headers.items():
        result.setdefault(key.lower(), []).append(value)
    return result


def build_aiohttp_response(method: str, uri: str, response: _HttpResponse) -> aiohttp.ClientResponse:

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
        writer=None,
        continue100=None,
        timer=None,  # type: ignore[arg-type]
        request_info=aiohttp.RequestInfo(
            url=URL(uri),
            method=method,
            headers=CIMultiDictProxy(CIMultiDict()),
            real_url=URL(uri),
        ),
        traces=[],
        loop=asyncio.get_running_loop(),
        session=None,  # type: ignore[arg-type]
    )
    resp.status = response.status
    resp._headers = CIMultiDictProxy(headers_multi)
    resp._body = content
    return resp
