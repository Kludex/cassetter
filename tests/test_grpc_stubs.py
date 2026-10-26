from __future__ import annotations

import struct
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

import grpc
import grpc.aio
import pytest
from google.protobuf.wrappers_pb2 import StringValue

from cassetter import Body, NoMatchError, ResponseMismatchError, use_cassette


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


async def fail(request: StringValue, context: grpc.aio.ServicerContext[Any, Any]) -> AsyncIterator[StringValue]:
    yield StringValue(value="a")
    await context.abort(grpc.StatusCode.INTERNAL, "boom")


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
            "Fail": grpc.unary_stream_rpc_method_handler(fail, **SERIALIZERS),
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


async def reused(*values: str) -> AsyncIterator[StringValue]:
    message = StringValue()
    for value in values:
        message.value = value
        yield message


async def call_streams_with_a_reused_message(channel: grpc.aio.Channel) -> list[list[str]]:
    stub = EchoStub(channel)
    return [
        [(await stub.Collect(reused("a", "b"))).value],
        values([response async for response in stub.Chat(reused("a", "b"))]),
    ]


@pytest.mark.anyio
async def test_streams_send_each_message_as_it_was_yielded(tmp_path: Path, target: str) -> None:
    path = tmp_path / "grpc.yaml"
    expected = [["a b"], ["echo a", "echo b"]]

    with use_cassette(path, record_mode="once", intercept=["grpc"]):
        channel = grpc.aio.insecure_channel(target)
        assert await call_streams_with_a_reused_message(channel) == expected

    async with channel:
        assert await call_streams_with_a_reused_message(channel) == expected

    with use_cassette(path, record_mode="none", intercept=["grpc"], match_on=["method", "body"]):
        async with grpc.aio.insecure_channel("localhost:1") as channel:
            assert await call_streams_with_a_reused_message(channel) == expected


@pytest.mark.anyio
async def test_body_matching_needs_the_request_body(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=[], match_on=["method", "body"]) as cassette:
        with pytest.raises(ValueError, match="needs the request_body"):
            cassette.play_grpc("/pkg.Echo/Say")


@pytest.mark.anyio
@pytest.mark.parametrize("body_matching", [False, True])
async def test_verify_sends_every_call_kind_live(recorded: Path, target: str, body_matching: bool) -> None:
    before = recorded.read_text()
    with use_cassette(
        recorded, record_mode="verify", intercept=["grpc"], match_on=["method", "body"] if body_matching else ["method"]
    ) as cassette:
        async with grpc.aio.insecure_channel(target) as channel:
            assert await call_every_kind(channel) == [["echo hi"], ["a", "b"], ["a b"], ["echo a", "echo b"]]
    assert cassette.all_played
    assert recorded.read_text() == before


@pytest.mark.anyio
async def test_verify_reports_a_different_response(tmp_path: Path, target: str) -> None:
    path = tmp_path / "grpc.yaml"
    with use_cassette(path, record_mode="once", intercept=["grpc"]):
        async with grpc.aio.insecure_channel(target) as channel:
            await EchoStub(channel).Say(StringValue(value="bye"))
            [response async for response in EchoStub(channel).Stream(StringValue(value="a"))]

    with use_cassette(path, record_mode="verify", intercept=["grpc"]):
        async with grpc.aio.insecure_channel(target) as channel:
            stub = EchoStub(channel)
            with pytest.raises(ResponseMismatchError) as mismatch:
                await stub.Say(StringValue(value="hi"))
            with pytest.raises(ResponseMismatchError, match=r" message 1: a\n\+message 2: b$"):
                [response async for response in stub.Stream(StringValue(value="a b"))]
    assert str(mismatch.value) == (
        f"cassette {path}, gRPC /pkg.Echo/Say\n--- recorded\n+++ live\n@@ -1,2 +1,2 @@\n status: 0 OK\n"
        "-message 1: echo bye\n+message 1: echo hi"
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "raised", "match"),
    [
        ((12, "Method not found!"), grpc.aio.AioRpcError, "Method not found!"),
        ((0, "OK"), ResponseMismatchError, "-status: 0 OK\n\\+status: 12 Method not found!"),
    ],
    ids=["same-error", "error-instead-of-ok"],
)
async def test_verify_compares_a_live_error_status(
    tmp_path: Path, target: str, status: tuple[int, str], raised: type[Exception], match: str
) -> None:
    path = tmp_path / "grpc.yaml"
    with use_cassette(path, record_mode="all", intercept=[]) as cassette:
        cassette.record_grpc("/pkg.Echo/Missing", {}, Body("binary", b""), Body("binary", b""), *status)

    with use_cassette(path, record_mode="verify", intercept=["grpc"]):
        async with grpc.aio.insecure_channel(target) as channel:
            missing = channel.unary_unary(
                "/pkg.Echo/Missing",
                request_serializer=StringValue.SerializeToString,
                response_deserializer=StringValue.FromString,
            )
            with pytest.raises(raised, match=match):
                await missing(StringValue(value="hi"))


def length_prefixed(*values: str) -> bytes:
    chunks = [StringValue(value=value).SerializeToString() for value in values]
    return b"".join(struct.pack(">I", len(chunk)) + chunk for chunk in chunks)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("recorded_values", "raised", "match"),
    [(["a"], grpc.aio.AioRpcError, "boom"), ([], ResponseMismatchError, r" status: 13 boom\n\+message 1: a$")],
    ids=["same-messages", "unexpected-message"],
)
async def test_verify_compares_messages_received_before_an_error(
    tmp_path: Path, target: str, recorded_values: list[str], raised: type[Exception], match: str
) -> None:
    path = tmp_path / "grpc.yaml"
    with use_cassette(path, record_mode="all", intercept=[]) as cassette:
        body = Body("binary", length_prefixed(*recorded_values))
        cassette.record_grpc("/pkg.Echo/Fail", {}, Body("binary", b""), body, 13, "boom")

    with use_cassette(path, record_mode="verify", intercept=["grpc"]):
        async with grpc.aio.insecure_channel(target) as channel:
            stream = channel.unary_stream(
                "/pkg.Echo/Fail",
                request_serializer=StringValue.SerializeToString,
                response_deserializer=StringValue.FromString,
            )
            with pytest.raises(raised, match=match):
                [response async for response in stream(StringValue(value="hi"))]


class Opaque:
    """A message type `google.protobuf` cannot convert to JSON."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    @classmethod
    def FromString(cls, data: bytes) -> Opaque:
        return cls(data)

    def SerializeToString(self) -> bytes:
        return self.data


@pytest.mark.anyio
async def test_verify_compares_messages_protobuf_cannot_convert_as_bytes(recorded: Path, target: str) -> None:
    with use_cassette(recorded, record_mode="verify", intercept=["grpc"]):
        async with grpc.aio.insecure_channel(target) as channel:
            say = channel.unary_unary(
                "/pkg.Echo/Say",
                request_serializer=StringValue.SerializeToString,
                response_deserializer=Opaque.FromString,
            )
            response = await say(StringValue(value="hi"))
    assert StringValue.FromString(response.data).value == "echo hi"
