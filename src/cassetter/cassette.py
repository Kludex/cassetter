from __future__ import annotations

import fnmatch
import os
import re
import warnings
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

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
    scrub_grpc_interaction,
    scrub_interaction,
    scrub_ws_interaction,
)
from cassetter.introspection import RecordedRequest, recorded_request
from cassetter.recording import RecordMode


class CassetteNotFoundError(Exception):
    """Raised when a cassette file is not found and record mode doesn't allow recording."""


class CassetteExpiredWarning(UserWarning):
    """Emitted when a cassette is older than the configured max_age."""


class CassetteExpiredError(Exception):
    """Raised when a cassette is older than the configured max_age and on_expiry is 'fail'."""


class NoMatchError(Exception):
    """Raised when no matching interaction is found in the cassette."""


class SkipRecording(Exception):
    """Raised from a before_record_request or before_record_response hook to skip recording."""


@dataclass(slots=True)
class RawRequest:
    """Raw HTTP request data passed to the before_record_request hook."""

    method: str
    uri: str
    headers: dict[str, list[str]]
    body: bytes | None


@dataclass(slots=True)
class RawResponse:
    """Raw HTTP response data passed to the before_record_response hook."""

    status: int
    headers: dict[str, list[str]]
    body: bytes | None


BeforeRecordRequest = Callable[[RawRequest], RawRequest]
BeforeRecordResponse = Callable[[RawResponse], RawResponse]


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
        path: str | os.PathLike[str],
        *,
        record_mode: RecordMode = RecordMode.ONCE,
        match_config: MatchConfig | None = None,
        security_config: SecurityConfig | None = None,
        max_age: str | None = None,
        on_expiry: str = "warn",
        ignore_localhost: bool = False,
        ignore_hosts: list[str] | None = None,
        before_record_request: BeforeRecordRequest | None = None,
        before_record_response: BeforeRecordResponse | None = None,
    ) -> None:
        self._path = os.fspath(path)
        self._record_mode = record_mode
        self._match_config = match_config or MatchConfig()
        self._security_config = security_config or SecurityConfig()
        self._max_age = _parse_duration(max_age) if max_age is not None else None
        self._on_expiry = on_expiry
        self._ignore_localhost = ignore_localhost
        self._ignore_hosts = ignore_hosts or []
        self._before_record_request = before_record_request
        self._before_record_response = before_record_response
        self._inner: _RustCassette | None = None
        self._dirty = False
        self._once_replay_only = False
        self._play_counter: Counter[int] = Counter()

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
    def before_record_request(self) -> BeforeRecordRequest | None:
        return self._before_record_request

    @property
    def before_record_response(self) -> BeforeRecordResponse | None:
        return self._before_record_response

    def should_bypass(self, uri: str) -> bool:
        """Check if a request URI should bypass the cassette entirely."""
        if self._ignore_localhost and _is_localhost(uri):
            return True
        if self._ignore_hosts:
            host = urlparse(uri).hostname or ""
            for pattern in self._ignore_hosts:
                if fnmatch.fnmatch(host, pattern):
                    return True
        return False

    @property
    def interactions(self) -> list[HttpInteraction]:
        if self._inner is None:
            return []
        return self._inner.interactions

    @property
    def requests(self) -> list[RecordedRequest]:
        """Recorded requests with vcrpy-compatible attributes."""
        return [recorded_request(i) for i in self.interactions]

    @property
    def played_indices(self) -> list[bool]:
        if self._inner is None:
            return []
        return self._inner.played_indices

    @property
    def play_count(self) -> int:
        """Total number of replays, counting repeats (vcrpy semantics)."""
        return sum(self._play_counter.values())

    @property
    def play_counts(self) -> Counter[int]:
        """Replay count per interaction index, counting repeats (vcrpy semantics)."""
        return Counter(self._play_counter)

    @property
    def all_played(self) -> bool:
        """Whether every recorded interaction has been replayed."""
        return all(self.played_indices)

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
        self._once_replay_only = True
        self._play_counter = Counter()
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
            self._once_replay_only = False
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
        if self._record_mode in (RecordMode.ALL, RecordMode.NEW_EPISODES):
            return True
        # `once` records only when the cassette didn't exist: with an existing
        # cassette an unmatched request must raise instead of silently hitting
        # the network and appending.
        return self._record_mode == RecordMode.ONCE and not self._once_replay_only

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
        # Interactions are scrubbed at write time, so the live request must be
        # scrubbed with the same config before matching: a URI recorded as
        # api_key=[FILTERED] would otherwise never match the real query string.
        probe = HttpInteraction(request, HttpResponse(0), "")
        request = scrub_interaction(probe, self._security_config).request
        result = find_match(request, self._inner.interactions, self._inner.played_indices, self._match_config)

        if result is None:
            raise NoMatchError(f"no matching interaction for {method} {uri}")

        idx, interaction = result
        self._inner.mark_played(idx)
        self._play_counter[idx] += 1
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
        # Apply before_record_response hook
        if self._before_record_response is not None:
            try:
                result = self._before_record_response(RawResponse(status, response_headers, response_body))
            except SkipRecording:
                resp_ct = _get_header(response_headers, "content-type")
                resp_ce = _get_header(response_headers, "content-encoding")
                resp_body = process_body(response_body or b"", resp_ct, resp_ce)
                clean_resp_headers = {k: v for k, v in response_headers.items() if k.lower() != "content-encoding"}
                return HttpResponse(status, clean_resp_headers, resp_body)
            status = result.status
            response_headers = result.headers
            response_body = result.body

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

        # Apply security filtering
        interaction = scrub_grpc_interaction(interaction, self._security_config)

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

        # Apply security filtering
        interaction = scrub_ws_interaction(interaction, self._security_config)

        if self._inner is None:
            self._inner = _RustCassette()

        self._inner.add_ws_interaction(interaction)
        self._dirty = True


_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


def _is_localhost(uri: str) -> bool:
    host = urlparse(uri).hostname or ""
    return host in _LOCALHOST_HOSTS


def _get_header(headers: dict[str, list[str]], name: str) -> str | None:
    """Case-insensitive header lookup, returns first value or None."""
    name_lower = name.lower()
    for key, values in headers.items():
        if key.lower() == name_lower and values:
            return values[0]
    return None
