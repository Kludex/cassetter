from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import grpc
import grpc.aio
import pytest
from google.protobuf.wrappers_pb2 import StringValue

from cassetter import use_cassette


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class EchoStub:
    """Shaped like the stubs `grpcio-tools` generates, which pass `_registered_method`."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self.Say = channel.unary_unary(
            "/pkg.Echo/Say",
            request_serializer=StringValue.SerializeToString,
            response_deserializer=StringValue.FromString,
            _registered_method=True,
        )
        self.Stream = channel.unary_stream(
            "/pkg.Echo/Stream",
            request_serializer=StringValue.SerializeToString,
            response_deserializer=StringValue.FromString,
            _registered_method=True,
        )
        self.Collect = channel.stream_unary(
            "/pkg.Echo/Collect",
            request_serializer=StringValue.SerializeToString,
            response_deserializer=StringValue.FromString,
            _registered_method=True,
        )
        self.Chat = channel.stream_stream(
            "/pkg.Echo/Chat",
            request_serializer=StringValue.SerializeToString,
            response_deserializer=StringValue.FromString,
            _registered_method=True,
        )


async def say(request: StringValue, context: object) -> StringValue:
    return StringValue(value=f"echo {request.value}")


@pytest.fixture
async def target() -> AsyncIterator[str]:
    handler = grpc.method_handlers_generic_handler(
        "pkg.Echo",
        {
            "Say": grpc.unary_unary_rpc_method_handler(
                say,
                request_deserializer=StringValue.FromString,
                response_serializer=StringValue.SerializeToString,
            )
        },
    )
    server = grpc.aio.server()
    server.add_generic_rpc_handlers((handler,))
    port = server.add_insecure_port("localhost:0")
    await server.start()
    yield f"localhost:{port}"
    await server.stop(None)


@pytest.mark.anyio
async def test_generated_stub_records_and_replays(tmp_path: Path, target: str) -> None:
    path = tmp_path / "grpc.yaml"

    with use_cassette(path, record_mode="once", intercept=["grpc"]):
        async with grpc.aio.insecure_channel(target) as channel:
            response = await EchoStub(channel).Say(StringValue(value="hi"))
    assert response.value == "echo hi"

    with use_cassette(path, record_mode="none", intercept=["grpc"]):
        async with grpc.aio.insecure_channel("localhost:1") as channel:
            response = await EchoStub(channel).Say(StringValue(value="hi"))
    assert response.value == "echo hi"
