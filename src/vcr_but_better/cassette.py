from __future__ import annotations

import os
from datetime import datetime, timezone

from vcr_but_better._core import (
    Cassette as _RustCassette,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    MatchConfig,
    SecurityConfig,
    find_match,
    process_body,
    scrub_interaction,
)
from vcr_but_better.recording import RecordMode


class CassetteNotFoundError(Exception):
    """Raised when a cassette file is not found and record mode doesn't allow recording."""


class NoMatchError(Exception):
    """Raised when no matching interaction is found in the cassette."""


class Cassette:
    """Python wrapper around the Rust Cassette providing record/replay logic."""

    def __init__(
        self,
        path: str,
        *,
        record_mode: RecordMode = RecordMode.ONCE,
        match_config: MatchConfig | None = None,
        security_config: SecurityConfig | None = None,
    ) -> None:
        self._path = path
        self._record_mode = record_mode
        self._match_config = match_config or MatchConfig()
        self._security_config = security_config or SecurityConfig()
        self._inner: _RustCassette | None = None
        self._dirty = False

    @property
    def path(self) -> str:
        return self._path

    @property
    def record_mode(self) -> RecordMode:
        return self._record_mode

    @property
    def interactions(self) -> list[HttpInteraction]:
        if self._inner is None:
            return []
        return self._inner.interactions

    def load(self) -> None:
        """Load the cassette from disk, or create a new one based on record mode."""
        exists = os.path.exists(self._path)

        if self._record_mode == RecordMode.NONE and not exists:
            raise CassetteNotFoundError(f"cassette not found: {self._path}")

        if self._record_mode == RecordMode.ALL or not exists:
            self._inner = _RustCassette()
            if self._record_mode == RecordMode.ALL:
                self._dirty = True
            return

        self._inner = _RustCassette.load(self._path)

    def save(self) -> None:
        """Save the cassette to disk if it has been modified."""
        if self._inner is not None and self._dirty:
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
        result = find_match(request, self._inner.interactions, self._match_config)

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
        clean_resp_headers = {
            k: v for k, v in response_headers.items() if k.lower() != "content-encoding"
        }

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

    def play_or_record(
        self,
        method: str,
        uri: str,
        request_headers: dict[str, list[str]],
        request_body: bytes | None,
        real_fetch: object,
    ) -> HttpResponse:
        """Try to play a matching interaction. If none found and recording is allowed, fetch for real and record."""
        try:
            return self.play(method, uri, request_headers, request_body)
        except NoMatchError:
            if not self.can_record:
                raise
            # real_fetch is handled by the caller (interceptor) - this method is not used directly
            raise


def _get_header(headers: dict[str, list[str]], name: str) -> str | None:
    """Case-insensitive header lookup, returns first value or None."""
    name_lower = name.lower()
    for key, values in headers.items():
        if key.lower() == name_lower and values:
            return values[0]
    return None
