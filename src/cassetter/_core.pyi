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

class GrpcRequest:
    method: str
    metadata: dict[str, list[str]]
    body: Body

    def __init__(
        self,
        method: str,
        metadata: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> None: ...

class GrpcResponse:
    status_code: int
    status_message: str
    metadata: dict[str, list[str]]
    body: Body

    def __init__(
        self,
        status_code: int,
        status_message: str | None = None,
        metadata: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> None: ...

class GrpcInteraction:
    request: GrpcRequest
    response: GrpcResponse
    json_debug: Any
    recorded_at: str

    def __init__(
        self,
        request: GrpcRequest,
        response: GrpcResponse,
        recorded_at: str,
        json_debug: Any = None,
    ) -> None: ...

class WsFrame:
    direction: str
    frame_type: str
    body: Body
    offset_ms: int

    def __init__(
        self,
        direction: str,
        frame_type: str,
        body: Body,
        offset_ms: int = 0,
    ) -> None: ...

class WsInteraction:
    uri: str
    headers: dict[str, list[str]]
    frames: list[WsFrame]
    recorded_at: str

    def __init__(
        self,
        uri: str,
        headers: dict[str, list[str]] | None = None,
        frames: list[WsFrame] | None = None,
        recorded_at: str | None = None,
    ) -> None: ...

class Cassette:
    version: int
    interactions: list[HttpInteraction]
    played_indices: list[bool]
    grpc_interactions: list[GrpcInteraction]
    grpc_played: list[bool]
    ws_interactions: list[WsInteraction]
    ws_played: list[bool]
    unplayed_count: int

    def __init__(self) -> None: ...
    def add_interaction(self, interaction: HttpInteraction) -> None: ...
    def mark_played(self, index: int) -> None: ...
    def add_grpc_interaction(self, interaction: GrpcInteraction) -> None: ...
    def mark_grpc_played(self, index: int) -> None: ...
    def add_ws_interaction(self, interaction: WsInteraction) -> None: ...
    def mark_ws_played(self, index: int) -> None: ...
    @staticmethod
    def load(path: str) -> Cassette: ...
    def save(self, path: str) -> None: ...
    def __len__(self) -> int: ...
    def __repr__(self) -> str: ...

class MatchConfig:
    match_on: list[str]
    ignore_json_paths: list[str]

    def __init__(
        self,
        match_on: list[str] | None = None,
        ignore_json_paths: list[str] | None = None,
    ) -> None: ...

class SecurityConfig:
    filter_headers: list[str]
    filter_query_parameters: list[str]
    body_scrub_patterns: list[str]
    replacement: str

    def __init__(
        self,
        filter_headers: list[str] | None = None,
        filter_query_parameters: list[str] | None = None,
        body_scrub_patterns: list[str] | None = None,
        replacement: str | None = None,
    ) -> None: ...

def find_match(
    request: HttpRequest,
    interactions: list[HttpInteraction],
    played: list[bool],
    config: MatchConfig,
) -> tuple[int, HttpInteraction] | None: ...
def find_grpc_match(
    method: str,
    interactions: list[GrpcInteraction],
    played: list[bool],
) -> tuple[int, GrpcInteraction] | None: ...
def find_ws_match(
    uri: str,
    interactions: list[WsInteraction],
    played: list[bool],
) -> tuple[int, WsInteraction] | None: ...
def scrub_interaction(interaction: HttpInteraction, config: SecurityConfig) -> HttpInteraction: ...
def scrub_grpc_interaction(interaction: GrpcInteraction, config: SecurityConfig) -> GrpcInteraction: ...
def scrub_ws_interaction(interaction: WsInteraction, config: SecurityConfig) -> WsInteraction: ...
def process_body(
    raw_bytes: bytes,
    content_type: str | None = None,
    content_encoding: str | None = None,
) -> Body: ...
