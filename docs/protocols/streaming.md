# Streaming and SSE

SSE (Server-Sent Events) responses work out of the box. This is the streaming mechanism used by OpenAI, Anthropic, Groq, and most other LLM APIs, which makes it one of the most common reasons to record cassettes in the first place.

Nothing to configure:

```python
from cassetter import use_cassette

with use_cassette("cassette.yaml", record_mode="once"):
    with client.messages.stream(  # your LLM SDK of choice
        model="claude-sonnet-5",
        messages=[{"role": "user", "content": "Hello!"}],
        max_tokens=1024,
    ) as stream:
        for text in stream.text_stream:
            print(text, end="")
```

## The cassette

The full response body is recorded as readable text:

```yaml
response:
  status: 200
  headers:
    content-type:
      - text/event-stream
  body:
    type: text
    content: |+
      data: {"id":"chatcmpl-abc","choices":[{"delta":{"role":"assistant"}}]}

      data: {"id":"chatcmpl-abc","choices":[{"delta":{"content":"Hello"}}]}

      data: [DONE]
```

You can read every event, and diffs show exactly which chunk changed.

## How replay works

On replay, the buffered body is returned to the client SDK, which parses the SSE events from it.

Chunk boundaries are not preserved. That is fine for SSE: parsers split events on `\n\n` boundaries regardless of how the bytes were delivered on the wire. Your SDK sees the same events in the same order.

!!! note
    This matches how VCR.py handles streaming responses, so cassettes recorded for streaming endpoints behave the same way after migrating.
