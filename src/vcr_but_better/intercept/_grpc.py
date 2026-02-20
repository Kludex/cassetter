from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import grpc
import grpc.aio

from vcr_but_better._core import Body, GrpcResponse
from vcr_but_better.cassette import Cassette, NoMatchError


class VCRUnaryUnaryCallable:
    """Wraps a unary-unary gRPC callable for record/replay."""

    def __init__(
        self,
        method: str,
        real_callable: grpc.aio.UnaryUnaryMultiCallable[Any, Any],
        cassette: Cassette,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> None:
        self._method = method
        self._real = real_callable
        self._cassette = cassette
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
        req_bytes: bytes = self._request_serializer(request)
        req_body = Body("binary", req_bytes)
        md = _metadata_to_dict(metadata)

        try:
            grpc_resp = self._cassette.play_grpc(self._method)
            return _deserialize_body(grpc_resp, self._response_deserializer)
        except NoMatchError:
            if not self._cassette.can_record:
                raise

        response = await self._real(
            request,
            timeout=timeout,
            metadata=metadata,
            credentials=credentials,
            wait_for_ready=wait_for_ready,
            compression=compression,
        )
        resp_bytes: bytes = self._request_serializer.__self__.__class__.SerializeToString(response)  # type: ignore[union-attr]
        resp_body = Body("binary", resp_bytes)

        json_debug = _build_json_debug(request, response)

        self._cassette.record_grpc(
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
        real_callable: grpc.aio.UnaryStreamMultiCallable[Any, Any],
        cassette: Cassette,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> None:
        self._method = method
        self._real = real_callable
        self._cassette = cassette
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
    ) -> AsyncIterator[Any]:
        req_bytes: bytes = self._request_serializer(request)
        req_body = Body("binary", req_bytes)
        md = _metadata_to_dict(metadata)

        try:
            grpc_resp = self._cassette.play_grpc(self._method)
            return _replay_stream(grpc_resp, self._response_deserializer)
        except NoMatchError:
            if not self._cassette.can_record:
                raise

        return self._record_stream(request, req_body, md, timeout, metadata, credentials, wait_for_ready, compression)

    async def _record_stream(
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
            yield response  # type: ignore[misc]

        combined = b"".join(chunks)
        resp_body = Body("binary", combined)
        self._cassette.record_grpc(
            method=self._method,
            metadata=md,
            request_body=req_body,
            response_body=resp_body,
        )


class VCRChannel:
    """Wraps a real grpc.aio.Channel to intercept stub method calls."""

    def __init__(self, real_channel: grpc.aio.Channel, cassette: Cassette) -> None:
        self._real = real_channel
        self._cassette = cassette

    def unary_unary(
        self,
        method: str,
        request_serializer: Any = None,
        response_deserializer: Any = None,
    ) -> VCRUnaryUnaryCallable:
        real_callable = self._real.unary_unary(method, request_serializer, response_deserializer)
        return VCRUnaryUnaryCallable(method, real_callable, self._cassette, request_serializer, response_deserializer)

    def unary_stream(
        self,
        method: str,
        request_serializer: Any = None,
        response_deserializer: Any = None,
    ) -> VCRUnaryStreamCallable:
        real_callable = self._real.unary_stream(method, request_serializer, response_deserializer)
        return VCRUnaryStreamCallable(method, real_callable, self._cassette, request_serializer, response_deserializer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    async def close(self) -> None:
        await self._real.close()  # type: ignore[misc]

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
        self._cassette: Cassette | None = None

    def install(self, cassette: Cassette) -> None:
        self._cassette = cassette
        self._original_insecure = grpc.aio.insecure_channel
        self._original_secure = grpc.aio.secure_channel
        interceptor = self

        def patched_insecure(target: str, **kwargs: Any) -> VCRChannel:
            assert interceptor._original_insecure is not None
            assert interceptor._cassette is not None
            real = interceptor._original_insecure(target, **kwargs)
            return VCRChannel(real, interceptor._cassette)

        def patched_secure(target: str, credentials: Any, **kwargs: Any) -> VCRChannel:
            assert interceptor._original_secure is not None
            assert interceptor._cassette is not None
            real = interceptor._original_secure(target, credentials, **kwargs)
            return VCRChannel(real, interceptor._cassette)

        grpc.aio.insecure_channel = patched_insecure  # type: ignore[assignment]
        grpc.aio.secure_channel = patched_secure  # type: ignore[assignment]

    def uninstall(self) -> None:
        if self._original_insecure is not None:
            grpc.aio.insecure_channel = self._original_insecure  # type: ignore[assignment]
        if self._original_secure is not None:
            grpc.aio.secure_channel = self._original_secure  # type: ignore[assignment]
        self._cassette = None


def _metadata_to_dict(metadata: Any) -> dict[str, list[str]]:
    if metadata is None:
        return {}
    result: dict[str, list[str]] = {}
    for key, value in metadata:
        str_val = value if isinstance(value, str) else value.decode("utf-8", errors="replace")
        result.setdefault(key, []).append(str_val)
    return result


def _deserialize_body(grpc_resp: GrpcResponse, deserializer: Any) -> Any:
    body = grpc_resp.body
    if body.body_type == "binary" and isinstance(body.content, bytes):
        return deserializer(body.content)
    return deserializer(b"")


async def _replay_stream(grpc_resp: GrpcResponse, deserializer: Any) -> AsyncIterator[Any]:
    msg = _deserialize_body(grpc_resp, deserializer)
    yield msg  # type: ignore[misc]


def _build_json_debug(request: Any, response: Any) -> dict[str, Any] | None:
    try:
        from google.protobuf.json_format import MessageToDict

        return {
            "request": MessageToDict(request, preserving_proto_field_name=True),
            "response": MessageToDict(response, preserving_proto_field_name=True),
        }
    except (ImportError, AttributeError):
        return None
