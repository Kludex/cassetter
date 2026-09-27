from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import grpc
import grpc.aio
import pytest
from google.protobuf.wrappers_pb2 import StringValue

from cassetter import NoMatchError, use_cassette


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


async def stream(request: StringValue, context: object) -> AsyncIterator[StringValue]:
    for word in request.value.split():
        yield StringValue(value=word)


async def collect(requests: AsyncIterator[StringValue], context: object) -> StringValue:
    return StringValue(value=" ".join([request.value async for request in requests]))


async def chat(requests: AsyncIterator[StringValue], context: object) -> AsyncIterator[StringValue]:
    async for request in requests:
        yield StringValue(value=f"echo {request.value}")


async def messages(*values: str) -> AsyncIterator[StringValue]:
    for value in values:
        yield StringValue(value=value)


def values(responses: Iterable[StringValue]) -> list[str]:
    return [response.value for response in responses]


async def call_every_kind(channel: grpc.aio.Channel) -> list[list[str]]:
    stub = EchoStub(channel)
    return [
        [(await stub.Say(StringValue(value="hi"))).value],
        values([response async for response in stub.Stream(StringValue(value="a b"))]),
        [(await stub.Collect(messages("a", "b"))).value],
        values([response async for response in stub.Chat(messages("a", "b"))]),
    ]


SERIALIZERS = {"request_deserializer": StringValue.FromString, "response_serializer": StringValue.SerializeToString}


@pytest.fixture
async def target() -> AsyncIterator[str]:
    handler = grpc.method_handlers_generic_handler(
        "pkg.Echo",
        {
            "Say": grpc.unary_unary_rpc_method_handler(say, **SERIALIZERS),
            "Stream": grpc.unary_stream_rpc_method_handler(stream, **SERIALIZERS),
            "Collect": grpc.stream_unary_rpc_method_handler(collect, **SERIALIZERS),
            "Chat": grpc.stream_stream_rpc_method_handler(chat, **SERIALIZERS),
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


@pytest.mark.anyio
async def test_every_call_kind_records_and_replays(tmp_path: Path, target: str) -> None:
    path = tmp_path / "grpc.yaml"
    expected = [["echo hi"], ["a", "b"], ["a b"], ["echo a", "echo b"]]

    with use_cassette(path, record_mode="once", intercept=["grpc"]):
        async with grpc.aio.insecure_channel(target) as channel:
            assert await call_every_kind(channel) == expected

    with use_cassette(path, record_mode="none", intercept=["grpc"]):
        async with grpc.aio.insecure_channel("localhost:1") as channel:
            assert await call_every_kind(channel) == expected


@pytest.fixture
async def recorded(tmp_path: Path, target: str) -> Path:
    path = tmp_path / "grpc.yaml"
    with use_cassette(path, record_mode="once", intercept=["grpc"]):
        async with grpc.aio.insecure_channel(target) as channel:
            await call_every_kind(channel)
    return path


@pytest.mark.anyio
async def test_body_matching_replays_the_recorded_requests(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["grpc"], match_on=["method", "body"]):
        async with grpc.aio.insecure_channel("localhost:1") as channel:
            assert await call_every_kind(channel) == [["echo hi"], ["a", "b"], ["a b"], ["echo a", "echo b"]]


@pytest.mark.anyio
async def test_body_matching_rejects_a_different_request(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["grpc"], match_on=["method", "body"]):
        async with grpc.aio.insecure_channel("localhost:1") as channel:
            stub = EchoStub(channel)
            with pytest.raises(NoMatchError, match="with this request body"):
                await stub.Say(StringValue(value="bye"))
            with pytest.raises(NoMatchError):
                stub.Stream(StringValue(value="c d"))
            with pytest.raises(NoMatchError):
                await stub.Collect(messages("c"))
            with pytest.raises(NoMatchError):
                [response async for response in stub.Chat(messages("c"))]


@pytest.mark.anyio
async def test_a_different_request_replays_without_body_matching(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["grpc"]):
        async with grpc.aio.insecure_channel("localhost:1") as channel:
            assert (await EchoStub(channel).Say(StringValue(value="bye"))).value == "echo hi"


@pytest.mark.anyio
async def test_body_matching_records_a_new_bidi_request(recorded: Path, target: str) -> None:
    with use_cassette(recorded, record_mode="new_episodes", intercept=["grpc"], match_on=["method", "body"]):
        async with grpc.aio.insecure_channel(target) as channel:
            assert values([response async for response in EchoStub(channel).Chat(messages("c"))]) == ["echo c"]
