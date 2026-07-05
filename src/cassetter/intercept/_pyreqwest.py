from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pyreqwest_impersonate as pri

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import NoMatchError, RawRequest, SkipRecording

METHODS_WITH_BODY = frozenset({"post", "put", "patch"})
ALL_METHODS = ("get", "head", "options", "delete", "post", "put", "patch", "request")


@dataclass
class ReplayResponse:
    """Lightweight stand-in for pyreqwest_impersonate's native Response.

    The native ``Response`` cannot be constructed from Python, so we mimic its
    public interface for cassette playback.
    """

    status_code: int
    headers: dict[str, str]
    content: bytes
    url: str
    cookies: dict[str, str] = field(default_factory=dict)
    encoding: str = "UTF-8"

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    @property
    def text_plain(self) -> str:
        return self.text

    @property
    def text_markdown(self) -> str:
        return self.text

    def json(self) -> Any:
        return json.loads(self.content)


class PyreqwestInterceptor:
    """Intercepts pyreqwest_impersonate by patching every Client HTTP method."""

    def __init__(self) -> None:
        self._patchers: list[Any] = []

    def install(self) -> None:
        for method_name in ALL_METHODS:
            original = getattr(pri.Client, method_name)
            patcher = patch.object(
                pri.Client,
                method_name,
                make_wrapper(method_name, original),
            )
            patcher.start()
            self._patchers.append(patcher)

    def uninstall(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._patchers.clear()


def make_wrapper(
    method_name: str,
    original: Any,
) -> Any:
    if method_name == "request":

        def request_wrapper(client: Any, method: str, url: str, **kwargs: Any) -> Any:
            return intercept(original, client, method.upper(), url, (method, url), kwargs)

        return request_wrapper

    http_method = method_name.upper()

    def method_wrapper(client: Any, url: str, **kwargs: Any) -> Any:
        return intercept(original, client, http_method, url, (url,), kwargs)

    return method_wrapper


def intercept(
    original: Any,
    client: Any,
    method: str,
    url: str,
    original_args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    cassette = get_current_cassette()
    if cassette is None:  # pragma: no cover - patch active without a cassette context
        return original(client, *original_args, **kwargs)

    if cassette.should_bypass(url):
        return original(client, *original_args, **kwargs)

    norm_headers = extract_headers(kwargs.get("headers"))
    body = extract_body(
        content=kwargs.get("content"),
        data=kwargs.get("data"),
        json_payload=kwargs.get("json"),
    )

    hook = cassette.before_record_request
    if hook is not None:
        try:
            raw = hook(RawRequest(method, url, norm_headers, body))
        except SkipRecording:
            return original(client, *original_args, **kwargs)
        method, url, norm_headers, body = raw.method, raw.uri, raw.headers, raw.body

    try:
        response = cassette.play(method, url, norm_headers, body)
        return build_replay_response(url, response)
    except NoMatchError:
        if not cassette.can_record:
            raise

    real_response = original(client, *original_args, **kwargs)
    # pyreqwest decompresses the body, so drop content-encoding to prevent
    # double-decompression when recording
    resp_headers = extract_headers(real_response.headers)
    resp_headers.pop("content-encoding", None)

    cassette.record(
        method=method,
        # record the request URL: replay matches on it, and real_response.url
        # is post-redirect/normalized so it would never match
        uri=url,
        request_headers=norm_headers,
        request_body=body,
        status=real_response.status_code,
        response_headers=resp_headers,
        response_body=real_response.content,
    )
    return real_response


def extract_headers(headers: dict[str, str] | None) -> dict[str, list[str]]:
    if headers is None:
        return {}
    return {k.lower(): [v] for k, v in headers.items()}


def extract_body(
    *,
    content: bytes | None,
    data: dict[str, str] | str | None,
    json_payload: Any,
) -> bytes | None:
    if content is not None:
        return content
    if data is not None:
        if isinstance(data, bytes):
            return data
        if isinstance(data, str):
            return data.encode()
    if json_payload is not None:
        return json.dumps(json_payload).encode()
    return None


def build_replay_response(url: str, response: _HttpResponse) -> ReplayResponse:
    body = response.body
    if body.body_type == "json":
        content = json.dumps(body.content).encode()
    elif body.body_type == "text":
        content = body.content.encode() if isinstance(body.content, str) else b""
    elif body.body_type == "binary":
        content = body.content if isinstance(body.content, bytes) else b""
    else:
        content = b""

    flat_headers: dict[str, str] = {}
    for key, values in response.headers.items():
        flat_headers[key] = values[-1] if values else ""

    return ReplayResponse(
        status_code=response.status,
        headers=flat_headers,
        content=content,
        url=url,
    )
