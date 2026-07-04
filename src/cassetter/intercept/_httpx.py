from __future__ import annotations

from typing import cast

import httpx

from cassetter._core import HttpResponse as _HttpResponse
from cassetter.intercept._httpx_impl import (
    build_response,
    extract_headers as extract_headers,
    extract_headers_skip_encoding as extract_headers_skip_encoding,
    make_interceptor,
)

HttpxInterceptor = make_interceptor(httpx)


def build_httpx_response(response: _HttpResponse, request: httpx.Request | None = None) -> httpx.Response:
    return cast(httpx.Response, build_response(httpx, response, request))
