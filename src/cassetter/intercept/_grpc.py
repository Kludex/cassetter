from __future__ import annotations

import struct
from collections.abc import AsyncIterator
from typing import Any

import grpc
import grpc.aio

from cassetter._core import Body, GrpcResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import NoMatchError


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
        if cassette is None:
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
        md = _metadata_to_dict(metadata)

        try:
            grpc_resp = cassette.play_grpc(self._method)
            content = grpc_resp.body.content if isinstance(grpc_resp.body.content, bytes) else b""
            return self._response_deserializer(content)
        except NoMatchError:
            if not cassette.can_record:
                raise

        assert self._real is not None
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

        json_debug = _build_json_debug(request, response)

        cassette.record_grpc(
            method=self._method,
            metadata=md,
            request_body=req_body,
            response_body=resp_body,
            json_debug=json_debug,
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
        if cassette is None:
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
        md = _metadata_to_dict(metadata)

        try:
            grpc_resp = cassette.play_grpc(self._method)
            return _replay_stream(grpc_resp, self._response_deserializer)
        except NoMatchError:
            if not cassette.can_record:
                raise

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
        chunks: list[bytes] = []
        async for response in call:
            resp_bytes = response.SerializeToString()
            chunks.append(resp_bytes)
            yield response
        resp_body = Body("binary", _encode_chunks(chunks))
        if cassette is not None:
            cassette.record_grpc(
                method=self._method,
                metadata=md,
                request_body=req_body,
                response_body=resp_body,
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
                request_iterator,
                timeout=timeout,
                metadata=metadata,
                credentials=credentials,
                wait_for_ready=wait_for_ready,
                compression=compression,
            )

        md = _metadata_to_dict(metadata)
        req_chunks: list[bytes] = []
        async for req in request_iterator:
            req_chunks.append(self._request_serializer(req))
        req_body = Body("binary", _encode_chunks(req_chunks))

        try:
            grpc_resp = cassette.play_grpc(self._method)
            content = grpc_resp.body.content if isinstance(grpc_resp.body.content, bytes) else b""
            return self._response_deserializer(content)
        except NoMatchError:
            if not cassette.can_record:
                raise

        assert self._real is not None
        response = await self._real(
            _iter_bytes(req_chunks, self._response_deserializer),
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
            json_debug=_build_json_debug(None, response),
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
                request_iterator,
                timeout=timeout,
                metadata=metadata,
                credentials=credentials,
                wait_for_ready=wait_for_ready,
                compression=compression,
            )

        md = _metadata_to_dict(metadata)

        try:
            grpc_resp = cassette.play_grpc(self._method)
            return _replay_stream(grpc_resp, self._response_deserializer)
        except NoMatchError:
            if not cassette.can_record:
                raise

        assert self._real is not None
        return self._record_bidi(request_iterator, md, timeout, metadata, credentials, wait_for_ready, compression)

    async def _record_bidi(
        self,
        request_iterator: AsyncIterator[Any],
        md: dict[str, list[str]],
        timeout: float | None,
        metadata: Any,
        credentials: Any,
        wait_for_ready: bool | None,
        compression: Any,
    ) -> AsyncIterator[Any]:
        cassette = get_current_cassette()
        # Collect all request chunks for recording
        req_chunks: list[bytes] = []
        async for req in request_iterator:
            req_chunks.append(self._request_serializer(req))
        req_body = Body("binary", _encode_chunks(req_chunks))

        assert self._real is not None
        call = self._real(
            _async_iter(req_chunks),
            timeout=timeout,
            metadata=metadata,
            credentials=credentials,
            wait_for_ready=wait_for_ready,
            compression=compression,
        )
        resp_chunks: list[bytes] = []
        async for response in call:
            resp_bytes = response.SerializeToString()
            resp_chunks.append(resp_bytes)
            yield response
        resp_body = Body("binary", _encode_chunks(resp_chunks))
        if cassette is not None:
            cassette.record_grpc(
                method=self._method,
                metadata=md,
                request_body=req_body,
                response_body=resp_body,
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
    ) -> VCRUnaryUnaryCallable:
        real_callable = self._real.unary_unary(method, request_serializer, response_deserializer)
        return VCRUnaryUnaryCallable(method, real_callable, request_serializer, response_deserializer)

    def unary_stream(
        self,
        method: str,
        request_serializer: Any = None,
        response_deserializer: Any = None,
    ) -> VCRUnaryStreamCallable:
        real_callable = self._real.unary_stream(method, request_serializer, response_deserializer)
        return VCRUnaryStreamCallable(method, real_callable, request_serializer, response_deserializer)

    def stream_unary(
        self,
        method: str,
        request_serializer: Any = None,
        response_deserializer: Any = None,
    ) -> VCRStreamUnaryCallable:
        real_callable = self._real.stream_unary(method, request_serializer, response_deserializer)
        return VCRStreamUnaryCallable(method, real_callable, request_serializer, response_deserializer)

    def stream_stream(
        self,
        method: str,
        request_serializer: Any = None,
        response_deserializer: Any = None,
    ) -> VCRStreamStreamCallable:
        real_callable = self._real.stream_stream(method, request_serializer, response_deserializer)
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

        def patched_insecure(target: str, **kwargs: Any) -> VCRChannel:  # pragma: no cover
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


def _encode_chunks(chunks: list[bytes]) -> bytes:
    """Concatenate chunks with 4-byte big-endian length prefixes."""
    parts: list[bytes] = []
    for chunk in chunks:
        parts.append(struct.pack(">I", len(chunk)))
        parts.append(chunk)
    return b"".join(parts)


def _decode_chunks(data: bytes) -> list[bytes]:
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


def _metadata_to_dict(metadata: Any) -> dict[str, list[str]]:
    if metadata is None:
        return {}
    result: dict[str, list[str]] = {}
    for key, value in metadata:
        str_val = value if isinstance(value, str) else value.decode("utf-8", errors="replace")
        result.setdefault(key, []).append(str_val)
    return result


async def _replay_stream(grpc_resp: GrpcResponse, deserializer: Any) -> AsyncIterator[Any]:
    body = grpc_resp.body
    data = body.content if isinstance(body.content, bytes) else b""
    chunks = _decode_chunks(data)
    if chunks:
        for chunk in chunks:
            yield deserializer(chunk)
    else:
        # Single message (non-chunked) fallback
        yield deserializer(data)


async def _async_iter(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


def _iter_bytes(chunks: list[bytes], deserializer: Any) -> AsyncIterator[Any]:
    """Re-create an async iterator of deserialized messages from raw bytes."""
    return _async_iter(chunks)


def _build_json_debug(request: Any, response: Any) -> dict[str, Any] | None:
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
