from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast
from urllib.parse import parse_qsl, urlparse

from cassetter._core import Body, HttpInteraction

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class RecordedRequest:
    """A recorded request, exposing vcrpy's `Request` attribute surface.

    `body` is the wire form of the recorded body: a JSON string for `json`
    bodies, the text for `text` bodies, bytes for `binary` bodies, and None
    for empty bodies.
    """

    method: str
    uri: str
    headers: dict[str, list[str]]
    body: str | bytes | None

    @property
    def scheme(self) -> str:
        return urlparse(self.uri).scheme

    @property
    def host(self) -> str | None:
        return urlparse(self.uri).hostname

    @property
    def port(self) -> int | None:
        parsed = urlparse(self.uri)
        if parsed.port is not None:
            return parsed.port
        return _DEFAULT_PORTS.get(parsed.scheme)

    @property
    def path(self) -> str:
        return urlparse(self.uri).path

    @property
    def query(self) -> list[tuple[str, str]]:
        return sorted(parse_qsl(urlparse(self.uri).query))


def recorded_request(interaction: HttpInteraction) -> RecordedRequest:
    request = interaction.request
    return RecordedRequest(
        method=request.method,
        uri=request.uri,
        headers=request.headers,
        body=_wire_body(request.body),
    )


def sent_request(method: str, uri: str, headers: dict[str, list[str]], body: bytes | None) -> RecordedRequest:
    """A request as the code under test sent it, with the body as text when it decodes as UTF-8."""
    wire: str | bytes | None = body or None
    if isinstance(wire, bytes):
        try:
            wire = wire.decode()
        except UnicodeDecodeError:
            pass
    # Copy the headers: a `before_record_request` hook may edit the request it is handed in place.
    return RecordedRequest(
        method=method, uri=uri, headers={name: list(values) for name, values in headers.items()}, body=wire
    )


def _wire_body(body: Body) -> str | bytes | None:
    if body.body_type == "json":
        return json.dumps(body.content)
    if body.body_type == "text":
        return cast(str, body.content)
    if body.body_type == "binary":
        return cast(bytes, body.content)
    return None
