# gRPC

Cassetter records and replays gRPC calls made with `grpc.aio`.

## Install

```console
$ uv add "cassetter[grpc]"
```

## Record and replay

Add `"grpc"` to the interceptor list:

```python
import grpc

from cassetter import use_cassette

with use_cassette("cassette.yaml", intercept=["grpc"]):
    channel = grpc.aio.insecure_channel("localhost:50051")
    stub = my_service_pb2_grpc.MyServiceStub(channel)
    response = await stub.Echo(my_service_pb2.EchoRequest(message="hello"))
```

All four gRPC call patterns are supported:

* unary-unary
* server streaming
* client streaming
* bidirectional streaming

## The cassette

gRPC interactions are stored in their own section. Bodies are binary protobuf, stored as hex:

```yaml
grpc_interactions:
  - request:
      method: /mypackage.MyService/Echo
      metadata: {}
      body:
        type: binary
        content: 0a0568656c6c6f
    response:
      status_code: 0
      status_message: OK
      metadata: {}
      body:
        type: binary
        content: 0a0568656c6c6f
    json_debug:
      request:
        message: hello
      response:
        message: hello
```

The `json_debug` section is optional and purely for humans: when `google.protobuf` is available, Cassetter adds a readable representation of the request and response messages, so you can tell what a cassette contains without decoding protobuf in your head.

Streaming responses use length prefixed binary encoding. Multiple response chunks are stored in a single body field and decoded back into individual messages on replay.

## Security filtering

The same write time filtering as HTTP applies:

* Sensitive **metadata** keys (like `authorization` and `x-api-key`) are stripped from requests and responses.
* The **`json_debug`** payload is scrubbed with the body scrub patterns, so a field like `password` shows up as `[FILTERED]`.

Binary protobuf bodies are stored as is, they cannot be pattern scrubbed.
