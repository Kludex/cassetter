from __future__ import annotations

from typing import cast

import httpx2

from cassetter._core import HttpResponse as _HttpResponse
from cassetter.intercept._httpx_impl import build_response, make_interceptor

Httpx2Interceptor = make_interceptor(httpx2)


def build_httpx2_response(response: _HttpResponse, request: httpx2.Request | None = None) -> httpx2.Response:
    return cast(httpx2.Response, build_response(httpx2, response, request))
