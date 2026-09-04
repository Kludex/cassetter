from __future__ import annotations

from typing import Any, Literal

BodyType = Literal["json", "text", "binary", "none"]
FrameType = Literal["text", "binary", "close"]
Direction = Literal["send", "recv"]
Matcher = Literal["method", "uri", "headers", "body", "json_body"]

# The protocol types below are frozen: attributes are read-only and assignment
# raises AttributeError. Use `replace()` to derive a modified copy.

class Body:
    @property
    def body_type(self) -> BodyType: ...
    @property
    def content(self) -> Any: ...
    def __init__(self, body_type: BodyType, content: Any = None) -> None: ...
    def __eq__(self, other: object) -> bool: ...

class HttpRequest:
    @property
    def method(self) -> str: ...
    @property
    def uri(self) -> str: ...
    @property
    def headers(self) -> dict[str, list[str]]: ...
    @property
    def body(self) -> Body: ...
    def __init__(
        self,
        method: str,
        uri: str,
        headers: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> None: ...
    def replace(
        self,
        *,
        method: str | None = None,
        uri: str | None = None,
        headers: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> HttpRequest: ...
    def __eq__(self, other: object) -> bool: ...

class HttpResponse:
    @property
    def status(self) -> int: ...
    @property
    def headers(self) -> dict[str, list[str]]: ...
    @property
    def body(self) -> Body: ...
    def __init__(
        self,
        status: int,
        headers: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> None: ...
    def replace(
        self,
        *,
        status: int | None = None,
        headers: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> HttpResponse: ...
    def __eq__(self, other: object) -> bool: ...

class HttpInteraction:
    @property
    def request(self) -> HttpRequest: ...
    @property
    def response(self) -> HttpResponse: ...
    @property
    def recorded_at(self) -> str: ...
    def __init__(self, request: HttpRequest, response: HttpResponse, recorded_at: str) -> None: ...
    def replace(
        self,
        *,
        request: HttpRequest | None = None,
        response: HttpResponse | None = None,
        recorded_at: str | None = None,
    ) -> HttpInteraction: ...
    def __eq__(self, other: object) -> bool: ...

class GrpcRequest:
    @property
    def method(self) -> str: ...
    @property
    def metadata(self) -> dict[str, list[str]]: ...
    @property
    def body(self) -> Body: ...
    def __init__(
        self,
        method: str,
        metadata: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> None: ...
    def replace(
        self,
        *,
        method: str | None = None,
        metadata: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> GrpcRequest: ...
    def __eq__(self, other: object) -> bool: ...

class GrpcResponse:
    @property
    def status_code(self) -> int: ...
    @property
    def status_message(self) -> str: ...
    @property
    def metadata(self) -> dict[str, list[str]]: ...
    @property
    def body(self) -> Body: ...
    def __init__(
        self,
        status_code: int,
        status_message: str | None = None,
        metadata: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> None: ...
    def replace(
        self,
        *,
        status_code: int | None = None,
        status_message: str | None = None,
        metadata: dict[str, list[str]] | None = None,
        body: Body | None = None,
    ) -> GrpcResponse: ...
    def __eq__(self, other: object) -> bool: ...

class GrpcInteraction:
    @property
    def request(self) -> GrpcRequest: ...
    @property
    def response(self) -> GrpcResponse: ...
    @property
    def json_debug(self) -> Any: ...
    @property
    def recorded_at(self) -> str: ...
    def __init__(
        self,
        request: GrpcRequest,
        response: GrpcResponse,
        recorded_at: str,
        json_debug: Any = None,
    ) -> None: ...
    def replace(
        self,
        *,
        request: GrpcRequest | None = None,
        response: GrpcResponse | None = None,
        recorded_at: str | None = None,
        json_debug: Any = None,
    ) -> GrpcInteraction: ...
    def __eq__(self, other: object) -> bool: ...

class WsFrame:
    @property
    def direction(self) -> Direction: ...
    @property
    def frame_type(self) -> FrameType: ...
    @property
    def body(self) -> Body: ...
    @property
    def offset_ms(self) -> int: ...
    def __init__(
        self,
        direction: Direction,
        frame_type: FrameType,
        body: Body,
        offset_ms: int = 0,
    ) -> None: ...
    def replace(
        self,
        *,
        direction: Direction | None = None,
        frame_type: FrameType | None = None,
        body: Body | None = None,
        offset_ms: int | None = None,
    ) -> WsFrame: ...
    def __eq__(self, other: object) -> bool: ...

class WsInteraction:
    @property
    def uri(self) -> str: ...
    @property
    def headers(self) -> dict[str, list[str]]: ...
    @property
    def frames(self) -> list[WsFrame]: ...
    @property
    def recorded_at(self) -> str: ...
    def __init__(
        self,
        uri: str,
        headers: dict[str, list[str]] | None = None,
        frames: list[WsFrame] | None = None,
        recorded_at: str | None = None,
    ) -> None: ...
    def replace(
        self,
        *,
        uri: str | None = None,
        headers: dict[str, list[str]] | None = None,
        frames: list[WsFrame] | None = None,
        recorded_at: str | None = None,
    ) -> WsInteraction: ...
    def __eq__(self, other: object) -> bool: ...

class Cassette:
    version: int
    interactions: list[HttpInteraction]
    grpc_interactions: list[GrpcInteraction]
    ws_interactions: list[WsInteraction]

    @property
    def played_indices(self) -> list[bool]: ...
    @property
    def grpc_played(self) -> list[bool]: ...
    @property
    def ws_played(self) -> list[bool]: ...
    @property
    def unplayed_count(self) -> int: ...
    def __init__(self) -> None: ...
    def add_interaction(self, interaction: HttpInteraction) -> None: ...
    def mark_played(self, index: int) -> None: ...
    def add_grpc_interaction(self, interaction: GrpcInteraction) -> None: ...
    def mark_grpc_played(self, index: int) -> None: ...
    def add_ws_interaction(self, interaction: WsInteraction) -> None: ...
    def mark_ws_played(self, index: int) -> None: ...
    def take_match(self, request: HttpRequest, config: MatchConfig) -> tuple[int, HttpInteraction] | None: ...
    def take_grpc_match(self, method: str) -> tuple[int, GrpcInteraction] | None: ...
    def take_ws_match(self, uri: str) -> tuple[int, WsInteraction] | None: ...
    @staticmethod
    def load(path: str) -> Cassette: ...
    def output_order(
        self,
        sort_config: MatchConfig | None = None,
        record_order: list[int] | None = None,
    ) -> list[int]: ...
    def save(self, path: str, order: list[int] | None = None, mode: int | None = None) -> None: ...
    def __len__(self) -> int: ...
    def __repr__(self) -> str: ...

class MatchConfig:
    match_on: list[Matcher]
    ignore_json_paths: list[str]

    def __init__(
        self,
        match_on: list[Matcher] | None = None,
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
    max_decompressed: int | None = None,
) -> Body: ...
