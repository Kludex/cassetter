from __future__ import annotations

import base64
import contextlib
import struct
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import grpc
import grpc.aio

from cassetter._core import Body, GrpcResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import Cassette, NoMatchError

_STATUS_BY_CODE = {sc.value[0]: sc for sc in grpc.StatusCode}


def raise_for_status(grpc_resp: GrpcResponse) -> None:
    """Replay a recorded non-OK gRPC status as the AioRpcError it originally was."""
    if grpc_resp.status_code == 0:
        return
    code = _STATUS_BY_CODE.get(grpc_resp.status_code, grpc.StatusCode.UNKNOWN)
    raise grpc.aio.AioRpcError(
        code=code,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details=grpc_resp.status_message,
    )


class VCRUnaryUnaryCallable:
    """Wraps a unary-unary gRPC callable for record/replay."""

    def __init__(
        self,
        method: str,
        real_callable: grpc.aio.UnaryUnaryMultiCallable[Any, Any] | None,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> None:
        self._method = method
        self._real = real_callable
        self._request_serializer = request_serializer
        self._response_deserializer = response_deserializer

    async def __call__(
        self,
        request: Any,
        *,
        timeout: float | None = None,
        metadata: Any = None,
        credentials: Any = None,
        wait_for_ready: bool | None = None,
        compression: Any = None,
    ) -> Any:
        cassette = get_current_cassette()
        if cassette is None:  # pragma: no cover - needs a live gRPC channel
            assert self._real is not None
            return await self._real(
                request,
                timeout=timeout,
                metadata=metadata,
                credentials=credentials,
                wait_for_ready=wait_for_ready,
                compression=compression,
            )

        req_bytes: bytes = self._request_serializer(request)
        req_body = Body("binary", req_bytes)
        md = metadata_to_dict(metadata)

        try:
            grpc_resp = cassette.play_grpc(self._method, req_body)
            if not cassette.verifies:
                raise_for_status(grpc_resp)
                return self._response_deserializer(body_bytes(grpc_resp))
        except NoMatchError:
            if not cassette.can_record:
                raise
            grpc_resp = None

        assert self._real is not None
        messages = unary_messages(self._response_deserializer)
        with verify_status(cassette, self._method, md, req_body, grpc_resp, messages, []):
            response = await self._real(
                request,
                timeout=timeout,
                metadata=metadata,
                credentials=credentials,
                wait_for_ready=wait_for_ready,
                compression=compression,
            )
        resp_bytes: bytes = response.SerializeToString()
        resp_body = Body("binary", resp_bytes)

        json_debug = build_json_debug(request, response)

        cassette.record_grpc(
            method=self._method,
            metadata=md,
            request_body=req_body,
            response_body=resp_body,
            json_debug=json_debug,
            expected=grpc_resp,
            messages=messages,
        )
        return response


class VCRUnaryStreamCallable:
    """Wraps a unary-stream (server streaming) gRPC callable for record/replay."""

    def __init__(
        self,
        method: str,
        real_callable: grpc.aio.UnaryStreamMultiCallable[Any, Any] | None,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> None:
        self._method = method
        self._real = real_callable
        self._request_serializer = request_serializer
        self._response_deserializer = response_deserializer

    def __call__(
        self,
        request: Any,
        *,
        timeout: float | None = None,
        metadata: Any = None,
        credentials: Any = None,
        wait_for_ready: bool | None = None,
        compression: Any = None,
    ) -> AsyncIterator[Any]:
        cassette = get_current_cassette()
        if cassette is None:  # pragma: no cover - needs a live gRPC channel
            assert self._real is not None
            return self._real(  # type: ignore[no-any-return]
                request,
                timeout=timeout,
                metadata=metadata,
                credentials=credentials,
                wait_for_ready=wait_for_ready,
                compression=compression,
            )

        req_bytes: bytes = self._request_serializer(request)
        req_body = Body("binary", req_bytes)
        md = metadata_to_dict(metadata)

        try:
            grpc_resp = cassette.play_grpc(self._method, req_body)
            if not cassette.verifies:
                return replay_stream(grpc_resp, self._response_deserializer)  # status raised on first iteration
        except NoMatchError:
            if not cassette.can_record:
                raise
            grpc_resp = None

        assert self._real is not None
        return self._record_unary_stream(
            request,
            req_body,
            md,
            timeout,
            metadata,
            credentials,
            wait_for_ready,
            compression,
            grpc_resp,
        )

    async def _record_unary_stream(
        self,
        request: Any,
        req_body: Body,
        md: dict[str, list[str]],
        timeout: float | None,
        metadata: Any,
        credentials: Any,
        wait_for_ready: bool | None,
        compression: Any,
        expected: GrpcResponse | None,
    ) -> AsyncIterator[Any]:
        cassette = get_current_cassette()
        assert self._real is not None
        call = self._real(
            request,
            timeout=timeout,
            metadata=metadata,
            credentials=credentials,
            wait_for_ready=wait_for_ready,
            compression=compression,
        )
        messages = stream_messages(self._response_deserializer)
        chunks: list[bytes] = []
        with verify_status(cassette, self._method, md, req_body, expected, messages, chunks):
            async for response in call:
                resp_bytes = response.SerializeToString()
                chunks.append(resp_bytes)
                yield response
        resp_body = Body("binary", encode_chunks(chunks))
        if cassette is not None:
            cassette.record_grpc(
                method=self._method,
                metadata=md,
                request_body=req_body,
                response_body=resp_body,
                expected=expected,
                messages=messages,
            )


class VCRStreamUnaryCallable:
    """Wraps a stream-unary (client streaming) gRPC callable for record/replay."""

    def __init__(
        self,
        method: str,
        real_callable: grpc.aio.StreamUnaryMultiCallable[Any, Any] | None,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> None:
        self._method = method
        self._real = real_callable
        self._request_serializer = request_serializer
        self._response_deserializer = response_deserializer

    async def __call__(
        self,
        request_iterator: AsyncIterator[Any],
        *,
        timeout: float | None = None,
        metadata: Any = None,
        credentials: Any = None,
        wait_for_ready: bool | None = None,
        compression: Any = None,
    ) -> Any:
        cassette = get_current_cassette()
        if cassette is None:
            assert self._real is not None
            return await self._real(
                serialize(request_iterator, self._request_serializer),
                timeout=timeout,
                metadata=metadata,
                credentials=credentials,
                wait_for_ready=wait_for_ready,
                compression=compression,
            )

        md = metadata_to_dict(metadata)
        req_chunks = [chunk async for chunk in serialize(request_iterator, self._request_serializer)]
        req_body = Body("binary", encode_chunks(req_chunks))

        try:
            grpc_resp = cassette.play_grpc(self._method, req_body)
            if not cassette.verifies:
                raise_for_status(grpc_resp)
                return self._response_deserializer(body_bytes(grpc_resp))
        except NoMatchError:
            if not cassette.can_record:
                raise
            grpc_resp = None

        assert self._real is not None
        messages = unary_messages(self._response_deserializer)
        with verify_status(cassette, self._method, md, req_body, grpc_resp, messages, []):
            response = await self._real(
                async_iter(req_chunks),
                timeout=timeout,
                metadata=metadata,
                credentials=credentials,
                wait_for_ready=wait_for_ready,
                compression=compression,
            )
        resp_bytes: bytes = response.SerializeToString()
        resp_body = Body("binary", resp_bytes)

        cassette.record_grpc(
            method=self._method,
            metadata=md,
            request_body=req_body,
            response_body=resp_body,
            json_debug=build_json_debug(None, response),
            expected=grpc_resp,
            messages=messages,
        )
        return response


class VCRStreamStreamCallable:
    """Wraps a stream-stream (bidi streaming) gRPC callable for record/replay."""

    def __init__(
        self,
        method: str,
        real_callable: grpc.aio.StreamStreamMultiCallable[Any, Any] | None,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> None:
        self._method = method
        self._real = real_callable
        self._request_serializer = request_serializer
        self._response_deserializer = response_deserializer

    def __call__(
        self,
        request_iterator: AsyncIterator[Any],
        *,
        timeout: float | None = None,
        metadata: Any = None,
        credentials: Any = None,
        wait_for_ready: bool | None = None,
        compression: Any = None,
    ) -> AsyncIterator[Any]:
        cassette = get_current_cassette()
        if cassette is None:
            assert self._real is not None
            return self._real(  # type: ignore[no-any-return]
                serialize(request_iterator, self._request_serializer),
                timeout=timeout,
                metadata=metadata,
                credentials=credentials,
                wait_for_ready=wait_for_ready,
                compression=compression,
            )

        md = metadata_to_dict(metadata)
        options = (timeout, metadata, credentials, wait_for_ready, compression)
        if "body" in cassette.match_config.match_on:
            return self._play_matching_body(cassette, request_iterator, md, options)

        try:
            grpc_resp = cassette.play_grpc(self._method)
            if not cassette.verifies:
                return replay_stream(grpc_resp, self._response_deserializer)  # status raised on first iteration
        except NoMatchError:
            if not cassette.can_record:
                raise
            grpc_resp = None

        assert self._real is not None
        return self._record_bidi(serialize(request_iterator, self._request_serializer), md, *options, grpc_resp)

    async def _play_matching_body(
        self,
        cassette: Cassette,
        request_iterator: AsyncIterator[Any],
        md: dict[str, list[str]],
        options: tuple[float | None, Any, Any, bool | None, Any],
    ) -> AsyncIterator[Any]:
        # ponytail: waits for the whole request stream, so a conversation that sends in reply to responses stalls.
        req_chunks = [chunk async for chunk in serialize(request_iterator, self._request_serializer)]
        try:
            grpc_resp = cassette.play_grpc(self._method, Body("binary", encode_chunks(req_chunks)))
        except NoMatchError:
            if not cassette.can_record:
                raise
            grpc_resp = None
        if grpc_resp is None or cassette.verifies:
            async for response in self._record_bidi(async_iter(req_chunks), md, *options, grpc_resp):
                yield response
            return
        async for response in replay_stream(grpc_resp, self._response_deserializer):
            yield response

    async def _record_bidi(
        self,
        requests: AsyncIterator[bytes],
        md: dict[str, list[str]],
        timeout: float | None,
        metadata: Any,
        credentials: Any,
        wait_for_ready: bool | None,
        compression: Any,
        expected: GrpcResponse | None,
    ) -> AsyncIterator[Any]:
        cassette = get_current_cassette()
        req_chunks = [chunk async for chunk in requests]
        req_body = Body("binary", encode_chunks(req_chunks))

        assert self._real is not None
        call = self._real(
            async_iter(req_chunks),
            timeout=timeout,
            metadata=metadata,
            credentials=credentials,
            wait_for_ready=wait_for_ready,
            compression=compression,
        )
        messages = stream_messages(self._response_deserializer)
        resp_chunks: list[bytes] = []
        with verify_status(cassette, self._method, md, req_body, expected, messages, resp_chunks):
            async for response in call:
                resp_bytes = response.SerializeToString()
                resp_chunks.append(resp_bytes)
                yield response
        resp_body = Body("binary", encode_chunks(resp_chunks))
        if cassette is not None:
            cassette.record_grpc(
                method=self._method,
                metadata=md,
                request_body=req_body,
                response_body=resp_body,
                expected=expected,
                messages=messages,
            )


class VCRChannel:
    """Wraps a real grpc.aio.Channel to intercept stub method calls."""

    def __init__(self, real_channel: grpc.aio.Channel) -> None:
        self._real = real_channel

    def unary_unary(
        self,
        method: str,
        request_serializer: Any = None,
        response_deserializer: Any = None,
        **kwargs: Any,
    ) -> VCRUnaryUnaryCallable:
        real_callable = self._real.unary_unary(method, request_serializer, response_deserializer, **kwargs)
        return VCRUnaryUnaryCallable(method, real_callable, request_serializer, response_deserializer)

    def unary_stream(
        self,
        method: str,
        request_serializer: Any = None,
        response_deserializer: Any = None,
        **kwargs: Any,
    ) -> VCRUnaryStreamCallable:
        real_callable = self._real.unary_stream(method, request_serializer, response_deserializer, **kwargs)
        return VCRUnaryStreamCallable(method, real_callable, request_serializer, response_deserializer)

    def stream_unary(
        self,
        method: str,
        request_serializer: Any = None,
        response_deserializer: Any = None,
        **kwargs: Any,
    ) -> VCRStreamUnaryCallable:
        # Requests reach the real call already serialized, so a message mutated after it was sent keeps its value.
        real_callable = self._real.stream_unary(method, None, response_deserializer, **kwargs)
        return VCRStreamUnaryCallable(method, real_callable, request_serializer, response_deserializer)

    def stream_stream(
        self,
        method: str,
        request_serializer: Any = None,
        response_deserializer: Any = None,
        **kwargs: Any,
    ) -> VCRStreamStreamCallable:
        # Requests reach the real call already serialized, so a message mutated after it was sent keeps its value.
        real_callable = self._real.stream_stream(method, None, response_deserializer, **kwargs)
        return VCRStreamStreamCallable(method, real_callable, request_serializer, response_deserializer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    async def close(self) -> None:
        await self._real.close()

    async def __aenter__(self) -> VCRChannel:
        await self._real.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._real.__aexit__(*args)


class GrpcInterceptor:
    """Patches grpc.aio channel creation to intercept gRPC calls."""

    def __init__(self) -> None:
        self._original_insecure: Any = None
        self._original_secure: Any = None

    def install(self) -> None:
        self._original_insecure = grpc.aio.insecure_channel
        self._original_secure = grpc.aio.secure_channel

        original_insecure = self._original_insecure
        original_secure = self._original_secure

        def patched_insecure(target: str, **kwargs: Any) -> VCRChannel:
            real = original_insecure(target, **kwargs)
            return VCRChannel(real)

        def patched_secure(target: str, credentials: Any, **kwargs: Any) -> VCRChannel:  # pragma: no cover
            real = original_secure(target, credentials, **kwargs)
            return VCRChannel(real)

        grpc.aio.insecure_channel = patched_insecure
        grpc.aio.secure_channel = patched_secure

    def uninstall(self) -> None:
        if self._original_insecure is not None:
            grpc.aio.insecure_channel = self._original_insecure
        if self._original_secure is not None:
            grpc.aio.secure_channel = self._original_secure


# ---------------------------------------------------------------------------
# Chunk encoding (length-prefixed binary)
# ---------------------------------------------------------------------------


def encode_chunks(chunks: list[bytes]) -> bytes:
    """Concatenate chunks with 4-byte big-endian length prefixes."""
    parts: list[bytes] = []
    for chunk in chunks:
        parts.append(struct.pack(">I", len(chunk)))
        parts.append(chunk)
    return b"".join(parts)


def decode_chunks(data: bytes) -> list[bytes]:
    """Decode length-prefixed chunks back to a list."""
    chunks: list[bytes] = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            break
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        offset += 4
        chunks.append(data[offset : offset + length])
        offset += length
    return chunks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def metadata_to_dict(metadata: Any) -> dict[str, list[str]]:
    if metadata is None:
        return {}
    result: dict[str, list[str]] = {}
    for key, value in metadata:
        if key.lower().endswith("-bin"):
            raw_value = value.encode() if isinstance(value, str) else value
            str_val = base64.b64encode(raw_value).decode("ascii")
        else:
            str_val = value if isinstance(value, str) else value.decode("utf-8", errors="replace")
        result.setdefault(key, []).append(str_val)
    return result


async def replay_stream(grpc_resp: GrpcResponse, deserializer: Any) -> AsyncIterator[Any]:
    raise_for_status(grpc_resp)
    data = body_bytes(grpc_resp)
    chunks = decode_chunks(data)
    if chunks:
        for chunk in chunks:
            yield deserializer(chunk)
    else:
        # Single message (non-chunked) fallback
        yield deserializer(data)


def body_bytes(grpc_resp: GrpcResponse) -> bytes:
    payload = grpc_resp.body.content
    return payload if isinstance(payload, bytes) else b""


@contextlib.contextmanager
def verify_status(
    cassette: Cassette | None,
    method: str,
    md: dict[str, list[str]],
    req_body: Body,
    expected: GrpcResponse | None,
    messages: Callable[[GrpcResponse], list[Any]],
    received: list[bytes],
) -> Iterator[None]:
    """In `verify` mode, compare a live error status, and the messages `received` before it, with the recording."""
    try:
        yield
    except grpc.aio.AioRpcError as exc:
        if cassette is not None and expected is not None:
            status = (exc.code().value[0], exc.details() or "")
            body = Body("binary", encode_chunks(received))
            cassette.record_grpc(method, md, req_body, body, *status, expected=expected, messages=messages)
        raise


def unary_messages(deserializer: Any) -> Callable[[GrpcResponse], list[Any]]:
    return lambda grpc_resp: [readable(deserializer, body_bytes(grpc_resp))]


def stream_messages(deserializer: Any) -> Callable[[GrpcResponse], list[Any]]:
    return lambda grpc_resp: [readable(deserializer, chunk) for chunk in decode_chunks(body_bytes(grpc_resp))]


def readable(deserializer: Any, data: bytes) -> Any:
    """The message as JSON when protobuf can convert it, otherwise its serialized bytes."""
    debug = build_json_debug(None, deserializer(data))
    return data if debug is None else debug["response"]


async def serialize(requests: AsyncIterator[Any], serializer: Any) -> AsyncIterator[bytes]:
    async for request in requests:
        yield serializer(request)


async def async_iter(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


def build_json_debug(request: Any, response: Any) -> dict[str, Any] | None:
    try:
        from google.protobuf.json_format import MessageToDict  # pragma: no cover

        result: dict[str, Any] = {}  # pragma: no cover
        if request is not None:  # pragma: no cover
            result["request"] = MessageToDict(request, preserving_proto_field_name=True)
        if response is not None:  # pragma: no cover
            result["response"] = MessageToDict(response, preserving_proto_field_name=True)
        return result or None  # pragma: no cover
    except (ImportError, AttributeError):
        return None
