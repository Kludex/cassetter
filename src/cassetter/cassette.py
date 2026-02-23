from __future__ import annotations

import os
import re
import warnings
from datetime import datetime, timedelta, timezone

from cassetter._core import (
    Body,
    Cassette as _RustCassette,
    GrpcInteraction,
    GrpcRequest,
    GrpcResponse,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    MatchConfig,
    SecurityConfig,
    WsFrame,
    WsInteraction,
    find_grpc_match,
    find_match,
    find_ws_match,
    process_body,
    scrub_interaction,
)
from cassetter.recording import RecordMode


class CassetteNotFoundError(Exception):
    """Raised when a cassette file is not found and record mode doesn't allow recording."""


class CassetteExpiredWarning(UserWarning):
    """Emitted when a cassette is older than the configured max_age."""


class CassetteExpiredError(Exception):
    """Raised when a cassette is older than the configured max_age and on_expiry is 'fail'."""


class NoMatchError(Exception):
    """Raised when no matching interaction is found in the cassette."""


_DURATION_RE = re.compile(r"^(\d+)([dhw])$")
_UNIT_MAP = {"d": "days", "h": "hours", "w": "weeks"}


def _parse_duration(s: str) -> timedelta:
    """Parse a duration string like '30d', '24h', '4w' into a timedelta."""
    m = _DURATION_RE.match(s)
    if m is None:
        raise ValueError(f"invalid duration string: {s!r} (expected <number><d|h|w>)")
    value, unit = int(m.group(1)), m.group(2)
    return timedelta(**{_UNIT_MAP[unit]: value})


class Cassette:
    """Python wrapper around the Rust Cassette providing record/replay logic."""

    def __init__(
        self,
        path: str,
        *,
        record_mode: RecordMode = RecordMode.ONCE,
        match_config: MatchConfig | None = None,
        security_config: SecurityConfig | None = None,
        max_age: str | None = None,
        on_expiry: str = "warn",
        ignore_localhost: bool = False,
    ) -> None:
        self._path = path
        self._record_mode = record_mode
        self._match_config = match_config or MatchConfig()
        self._security_config = security_config or SecurityConfig()
        self._max_age = _parse_duration(max_age) if max_age is not None else None
        self._on_expiry = on_expiry
        self._ignore_localhost = ignore_localhost
        self._inner: _RustCassette | None = None
        self._dirty = False

    @property
    def path(self) -> str:
        return self._path

    @property
    def record_mode(self) -> RecordMode:
        return self._record_mode

    @property
    def ignore_localhost(self) -> bool:
        return self._ignore_localhost

    @property
    def interactions(self) -> list[HttpInteraction]:
        if self._inner is None:
            return []
        return self._inner.interactions

    @property
    def grpc_interactions(self) -> list[GrpcInteraction]:
        if self._inner is None:
            return []
        return self._inner.grpc_interactions

    @property
    def ws_interactions(self) -> list[WsInteraction]:
        if self._inner is None:
            return []
        return self._inner.ws_interactions

    def load(self) -> None:
        """Load the cassette from disk, or create a new one based on record mode."""
        exists = os.path.exists(self._path)

        if self._record_mode == RecordMode.ALL or not exists:
            self._inner = _RustCassette()
            if self._record_mode == RecordMode.ALL:
                self._dirty = True
            return

        self._inner = _RustCassette.load(self._path)
        self._check_expiry()

    def _check_expiry(self) -> None:
        """Check if the cassette is expired based on max_age, and apply on_expiry action."""
        if self._max_age is None or self._inner is None:
            return

        newest = self._newest_recorded_at()
        if newest is None:
            return

        cutoff = datetime.now(timezone.utc) - self._max_age
        if newest >= cutoff:
            return

        age_days = (datetime.now(timezone.utc) - newest).days
        msg = f"cassette {self._path!r} is {age_days} days old (max_age={self._max_age})"

        if self._on_expiry == "fail":
            raise CassetteExpiredError(msg)
        if self._on_expiry == "rerecord":
            self._inner = _RustCassette()
            self._dirty = True
            return
        warnings.warn(msg, CassetteExpiredWarning, stacklevel=3)

    def _newest_recorded_at(self) -> datetime | None:
        """Return the newest recorded_at timestamp across all interaction types."""
        assert self._inner is not None  # caller guards this
        timestamps: list[str] = []
        for http_i in self._inner.interactions:
            timestamps.append(http_i.recorded_at)
        for grpc_i in self._inner.grpc_interactions:
            timestamps.append(grpc_i.recorded_at)
        for ws_i in self._inner.ws_interactions:
            timestamps.append(ws_i.recorded_at)
        if not timestamps:
            return None
        return max(datetime.fromisoformat(ts.replace("Z", "+00:00")) for ts in timestamps)

    def save(self) -> None:
        """Save the cassette to disk if modified and has any interactions."""
        if self._inner is not None and self._dirty and len(self._inner) > 0:
            self._inner.save(self._path)
            self._dirty = False

    @property
    def can_record(self) -> bool:
        return self._record_mode in (RecordMode.ALL, RecordMode.NEW_EPISODES, RecordMode.ONCE)

    def play(
        self,
        method: str,
        uri: str,
        headers: dict[str, list[str]],
        body: bytes | None,
    ) -> HttpResponse:
        """Find a matching response for the given request, or raise NoMatchError."""
        if self._inner is None:
            raise NoMatchError("cassette not loaded")

        content_type = _get_header(headers, "content-type")
        content_encoding = _get_header(headers, "content-encoding")
        processed_body = process_body(body or b"", content_type, content_encoding)

        request = HttpRequest(method, uri, headers, processed_body)
        result = find_match(request, self._inner.interactions, self._inner.played_indices, self._match_config)

        if result is None:
            raise NoMatchError(f"no matching interaction for {method} {uri}")

        idx, interaction = result
        self._inner.mark_played(idx)
        return interaction.response

    def record(
        self,
        method: str,
        uri: str,
        request_headers: dict[str, list[str]],
        request_body: bytes | None,
        status: int,
        response_headers: dict[str, list[str]],
        response_body: bytes | None,
    ) -> HttpResponse:
        """Record an interaction and return the response."""
        req_ct = _get_header(request_headers, "content-type")
        req_ce = _get_header(request_headers, "content-encoding")
        req_body = process_body(request_body or b"", req_ct, req_ce)

        resp_ct = _get_header(response_headers, "content-type")
        resp_ce = _get_header(response_headers, "content-encoding")
        resp_body = process_body(response_body or b"", resp_ct, resp_ce)

        # Remove content-encoding since we've already decompressed
        clean_resp_headers = {k: v for k, v in response_headers.items() if k.lower() != "content-encoding"}

        request = HttpRequest(method, uri, request_headers, req_body)
        response = HttpResponse(status, clean_resp_headers, resp_body)
        recorded_at = datetime.now(timezone.utc).isoformat()
        interaction = HttpInteraction(request, response, recorded_at)

        # Apply security filtering
        interaction = scrub_interaction(interaction, self._security_config)

        if self._inner is None:
            self._inner = _RustCassette()

        self._inner.add_interaction(interaction)
        self._dirty = True
        return interaction.response

    # --- gRPC ---

    def play_grpc(self, method: str) -> GrpcResponse:
        """Find a matching gRPC response for the given method, or raise NoMatchError."""
        if self._inner is None:
            raise NoMatchError("cassette not loaded")

        result = find_grpc_match(method, self._inner.grpc_interactions, self._inner.grpc_played)
        if result is None:
            raise NoMatchError(f"no matching gRPC interaction for {method}")

        idx, interaction = result
        self._inner.mark_grpc_played(idx)
        return interaction.response

    def record_grpc(
        self,
        method: str,
        metadata: dict[str, list[str]],
        request_body: Body,
        response_body: Body,
        status_code: int = 0,
        status_message: str = "OK",
        response_metadata: dict[str, list[str]] | None = None,
        json_debug: dict[str, object] | None = None,
    ) -> GrpcResponse:
        """Record a gRPC interaction and return the response."""
        request = GrpcRequest(method, metadata, request_body)
        response = GrpcResponse(status_code, status_message, response_metadata, response_body)
        recorded_at = datetime.now(timezone.utc).isoformat()
        interaction = GrpcInteraction(request, response, recorded_at, json_debug)

        if self._inner is None:
            self._inner = _RustCassette()

        self._inner.add_grpc_interaction(interaction)
        self._dirty = True
        return interaction.response

    # --- WebSocket ---

    def play_ws(self, uri: str) -> WsInteraction:
        """Find a matching WebSocket interaction for the given URI, or raise NoMatchError."""
        if self._inner is None:
            raise NoMatchError("cassette not loaded")

        result = find_ws_match(uri, self._inner.ws_interactions, self._inner.ws_played)
        if result is None:
            raise NoMatchError(f"no matching WebSocket interaction for {uri}")

        idx, interaction = result
        self._inner.mark_ws_played(idx)
        return interaction

    def record_ws(
        self,
        uri: str,
        headers: dict[str, list[str]],
        frames: list[WsFrame],
    ) -> None:
        """Record a WebSocket interaction."""
        recorded_at = datetime.now(timezone.utc).isoformat()
        interaction = WsInteraction(uri, headers, frames, recorded_at)

        if self._inner is None:
            self._inner = _RustCassette()

        self._inner.add_ws_interaction(interaction)
        self._dirty = True


def _get_header(headers: dict[str, list[str]], name: str) -> str | None:
    """Case-insensitive header lookup, returns first value or None."""
    name_lower = name.lower()
    for key, values in headers.items():
        if key.lower() == name_lower and values:
            return values[0]
    return None
