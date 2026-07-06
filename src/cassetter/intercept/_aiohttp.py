from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any
from unittest.mock import patch
from urllib.parse import urlencode

import aiohttp
import aiohttp.client_reqrep
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import NoMatchError
from cassetter.intercept._shared import apply_before_record_request, body_to_bytes


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
            if cassette is None:  # pragma: no cover - patch active without a cassette context
                return await original_request(session, method, str_or_url, **kwargs)

            uri = str(_build_full_url(session, str_or_url, kwargs.get("params")))

            if cassette.should_bypass(uri):
                return await original_request(session, method, str_or_url, **kwargs)

            headers = extract_request_headers(kwargs.get("headers"))
            body = extract_request_body(kwargs)

            norm_method = method.upper()

            raw = apply_before_record_request(cassette.before_record_request, norm_method, uri, headers, body)
            if raw is None:
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


def _build_full_url(session: aiohttp.ClientSession, str_or_url: str | URL, params: Any) -> URL:
    """Resolve the request URL the way aiohttp does: session base_url plus query params."""
    try:
        url = session._build_url(str_or_url)
    except AttributeError:  # pragma: no cover - very old aiohttp
        url = URL(str_or_url)
    if params:
        url = url.update_query(params)
    return url


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
        if isinstance(data, dict):
            # aiohttp sends dict data as application/x-www-form-urlencoded
            return urlencode(data).encode()
    if "json" in kwargs and kwargs["json"] is not None:
        return json.dumps(kwargs["json"]).encode()
    return None


def extract_response_headers(headers: CIMultiDictProxy[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower == "content-encoding":
            # aiohttp's read() returns the decompressed body; keeping the
            # header would double-decompress when recording
            continue
        result.setdefault(lower, []).append(value)
    return result


def build_aiohttp_response(method: str, uri: str, response: _HttpResponse) -> aiohttp.ClientResponse:

    content = body_to_bytes(response.body)

    headers_multi: CIMultiDict[str] = CIMultiDict()
    for key, values in response.headers.items():
        for v in values:
            headers_multi.add(key, v)

    # Build a mock-like response. aiohttp 3.14 renamed/added constructor
    # kwargs (stream_writer), so pass only what this version accepts.
    ctor_kwargs: dict[str, Any] = {
        "method": method,
        "url": URL(uri),
        "writer": None,
        "continue100": None,
        "timer": None,
        "request_info": aiohttp.RequestInfo(
            url=URL(uri),
            method=method,
            headers=CIMultiDictProxy(CIMultiDict()),
            real_url=URL(uri),
        ),
        "traces": [],
        "loop": asyncio.get_running_loop(),
        "session": None,
    }
    accepted = _client_response_params()
    ctor_kwargs = {k: v for k, v in ctor_kwargs.items() if k in accepted}
    if "stream_writer" in accepted:
        # aiohttp 3.14+: with writer=None ("request already sent"), the
        # constructor reads stream_writer.output_size
        ctor_kwargs["stream_writer"] = _StubStreamWriter()
    resp = aiohttp.ClientResponse(**ctor_kwargs)
    resp.status = response.status
    resp._headers = CIMultiDictProxy(headers_multi)
    resp._body = content
    return resp


def _client_response_params() -> frozenset[str]:
    return frozenset(inspect.signature(aiohttp.ClientResponse.__init__).parameters)


class _StubStreamWriter:
    """Minimal stand-in for the request's stream writer on replayed responses."""

    output_size = 0
