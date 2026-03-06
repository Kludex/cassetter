from __future__ import annotations

from typing import Any

from typing_extensions import Protocol, TypedDict

from cassetter.cassette import BeforeRecordRequest


class CassetteConfig(TypedDict, total=False):
    """Configuration for a cassette recording/playback session."""

    record_mode: str
    match_on: list[str]
    ignore_json_paths: list[str]
    filtered_headers: list[str]
    filtered_query_params: list[str]
    body_scrub_patterns: list[str]
    filter_replacement: str
    cassette_dir: str
    intercept: list[str]
    max_age: str
    on_expiry: str
    ignore_localhost: bool
    ignore_hosts: list[str]
    before_record_request: BeforeRecordRequest


class Interceptor(Protocol):
    """Protocol for HTTP library interceptors."""

    def install(self) -> None: ...
    def uninstall(self) -> None: ...


class AsyncInterceptor(Protocol):
    """Protocol for async HTTP library interceptors."""

    async def install(self) -> None: ...
    async def uninstall(self) -> None: ...


class RequestCallback(Protocol):
    """Called when an interceptor captures an outgoing request."""

    def __call__(
        self,
        method: str,
        uri: str,
        headers: dict[str, list[str]],
        body: bytes | None,
    ) -> Any: ...
