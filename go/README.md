# cassetter-go

Record and replay Go HTTP requests with the same structured YAML format as
[`cassetter`](https://github.com/Kludex/cassetter).

## Install

```bash
go get github.com/Kludex/cassetter/go
```

## Record and replay HTTP

```go
package main

import (
    "io"
    "net/http"

    "github.com/Kludex/cassetter/go"
)

func main() {
    client := &http.Client{
        Transport: cassetter.NewTransport(
            http.DefaultTransport,
            cassetter.WithPath("tests/cassettes/openai.yaml"),
            cassetter.WithRecordMode(cassetter.RecordModeNone),
        ),
    }

    response, err := client.Get("https://api.example.com/users")
    if err != nil {
        panic(err)
    }
    defer response.Body.Close()

    if _, err := io.ReadAll(response.Body); err != nil {
        panic(err)
    }
}
```

The transport matches each interaction once by HTTP method and URI. It is safe
to share between goroutines. Response bodies remain streaming. A recording is
written when the body reaches EOF or is closed.

`RecordModeOnce` is the default. It records when the cassette does not exist.
It only replays when the cassette already exists.

| Mode | Behavior |
|---|---|
| `RecordModeNone` | Replay only. Return `ErrNoMatch` for a miss. |
| `RecordModeOnce` | Record a new cassette or replay an existing one. |
| `RecordModeNewEpisodes` | Replay existing interactions and record misses. |
| `RecordModeAll` | Record every request and replace existing interactions. |
| `RecordModeRewrite` | Remove the cassette first, then record every request. |

## Secret filtering

Filtering happens before the cassette is written. Authorization headers,
cookies, common API key query parameters, and common JSON secret fields are
filtered by default.

```go
transport := cassetter.NewTransport(
    http.DefaultTransport,
    cassetter.WithPath("tests/cassettes/api.yaml"),
    cassetter.WithFilterHeaders("x-company-token"),
    cassetter.WithFilterQueryParameters("signature"),
    cassetter.WithBodyScrubPatterns("private_key"),
)
```

Each option adds to the safe defaults.

## Inspect, diff, and scrub

```bash
go install github.com/Kludex/cassetter/go/cmd/cassetter@latest

cassetter inspect tests/cassettes/openai.yaml
cassetter diff tests/cassettes/openai.yaml tests/cassettes/openai-new.yaml
cassetter scrub tests/cassettes/openai.yaml
cassetter scrub --header x-company-token input.yaml output.yaml
```

`cassetter diff` exits with status `1` when it finds a difference. This lets you use it in CI.

`cassetter scrub` rewrites the input atomically when you omit the output path.
It applies the same safe defaults as the HTTP transport. Pass `--force` to
overwrite a separate output file.

## Scope

The first release supports YAML cassettes and HTTP through
`http.RoundTripper`. `Load` exposes typed HTTP, gRPC, and WebSocket interactions,
and rewrites preserve unrecognized top-level protocol sections. gRPC interceptors
and WebSocket recording are planned.
