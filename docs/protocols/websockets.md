# WebSockets

Cassetter records and replays WebSocket connections made with the `websockets` library.

## Install

```console
$ uv add "cassetter[websockets]"
```

## Record and replay

Add `"websockets"` to the interceptor list:

```python
import websockets

from cassetter import use_cassette

with use_cassette("cassette.yaml", intercept=["websockets"]):
    async with websockets.connect("wss://ws.example.com/stream") as ws:
        await ws.send('{"subscribe": "ticker"}')
        data = await ws.recv()
```

## The cassette

Each frame is recorded with its direction, type, and timing offset:

```yaml
ws_interactions:
  - uri: wss://ws.example.com/stream
    headers: {}
    frames:
      - direction: send
        frame_type: text
        body:
          type: text
          content: '{"subscribe": "ticker"}'
        offset_ms: 0
      - direction: recv
        frame_type: text
        body:
          type: json
          content:
            price: 42.5
        offset_ms: 120
```

On replay, `recv()` returns the recorded frames in order, without a real connection. `send()` is a no-op. Both text and binary frames are supported.

The replayed connection behaves like the `websockets` connection it stands in for:

* `recv(decode=False)` returns a text frame as UTF-8 bytes, and `recv(decode=True)` returns a binary frame as text.
* Once the recorded close is received, `close_code` and `close_reason` hold its code and reason. They are `None` while the connection is open.
* After `close()`, `recv()` raises `ConnectionClosedOK`, and `close_code` holds the code you closed with.

## Security filtering

The same write time filtering as HTTP applies:

* Sensitive **handshake headers** (like `authorization` and `cookie`) are stripped.
* **Text and JSON frame bodies** are scrubbed with the body scrub patterns. An authentication frame like `{"access_token": "..."}` is stored with the token replaced by `[FILTERED]`.

Binary frames are stored as is.
