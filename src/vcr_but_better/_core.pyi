from __future__ import annotations

from typing import Any

class Body:
    body_type: str
    content: Any

    def __init__(self, body_type: str, content: Any = None) -> None: ...

class HttpRequest:
    method: str
    uri: str
    headers: dict[str, list[str]]
    body: Body

    def __init__(
        self,
        method: str,
        uri: str,
        headers: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> None: ...

class HttpResponse:
    status: int
    headers: dict[str, list[str]]
    body: Body

    def __init__(
        self,
        status: int,
        headers: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> None: ...

class HttpInteraction:
    request: HttpRequest
    response: HttpResponse
    recorded_at: str

    def __init__(self, request: HttpRequest, response: HttpResponse, recorded_at: str) -> None: ...

class Cassette:
    version: int
    interactions: list[HttpInteraction]
    played_indices: list[bool]
    unplayed_count: int

    def __init__(self) -> None: ...
    def add_interaction(self, interaction: HttpInteraction) -> None: ...
    def mark_played(self, index: int) -> None: ...
    @staticmethod
    def load(path: str) -> Cassette: ...
    def save(self, path: str) -> None: ...
    def __len__(self) -> int: ...

class MatchConfig:
    match_on: list[str]
    ignore_json_paths: list[str]

    def __init__(
        self,
        match_on: list[str] | None = None,
        ignore_json_paths: list[str] | None = None,
    ) -> None: ...

class SecurityConfig:
    filtered_headers: list[str]
    filtered_query_params: list[str]
    body_scrub_patterns: list[str]
    replacement: str

    def __init__(
        self,
        filtered_headers: list[str] | None = None,
        filtered_query_params: list[str] | None = None,
        body_scrub_patterns: list[str] | None = None,
        replacement: str | None = None,
    ) -> None: ...

def find_match(
    request: HttpRequest,
    interactions: list[HttpInteraction],
    played: list[bool],
    config: MatchConfig,
) -> tuple[int, HttpInteraction] | None: ...
def scrub_interaction(interaction: HttpInteraction, config: SecurityConfig) -> HttpInteraction: ...
def process_body(
    raw_bytes: bytes,
    content_type: str | None = None,
    content_encoding: str | None = None,
) -> Body: ...
