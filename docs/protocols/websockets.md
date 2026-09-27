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

## Patch a reference an SDK already imported

The `websockets` interceptor replaces `websockets.connect`. An SDK that imported `connect` under its own name keeps the original: `google.genai.live` calls `ws_connect`, which the interceptor never touches. Point that name at `cassetter.websockets.connect`:

```python
import google.genai.live
import pytest

import cassetter.websockets


@pytest.fixture(autouse=True)
def record_gemini_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google.genai.live, "ws_connect", cassetter.websockets.connect)
```

`cassetter.websockets.connect` accepts the same arguments as `websockets.connect`. Inside a cassette it records or replays, whether or not `"websockets"` is in `intercept`. Outside a cassette, and for bypassed hosts, it opens a live connection.

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
* Once the recorded close is received, `close_code` and `close_reason` hold its code and reason. They are `None` while the connection is open. A recording without a close frame ends as a normal closure, code `1000`.
* After `close()`, `close_code` holds the code you closed with.
* Once the connection is closed, `send()` and `recv()` raise `ConnectionClosedOK` for a normal close code (`1000`, `1001`, or `1005`) and `ConnectionClosedError` for any other.

## Security filtering

The same write time filtering as HTTP applies:

* Sensitive **handshake headers** (like `authorization` and `cookie`) are stripped.
* **Text and JSON frame bodies** are scrubbed with the body scrub patterns. An authentication frame like `{"access_token": "..."}` is stored with the token replaced by `[FILTERED]`.

Binary frames are stored as is.
