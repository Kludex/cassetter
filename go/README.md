# cassetter-go

Record and replay Go HTTP requests with the same structured YAML and TOML formats as
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

The transport matches by HTTP method and URI. It prefers an unused interaction,
then reuses the first matching interaction after every match has played. It is
safe to share between goroutines. Response bodies remain streaming. A recording
is written when the body reaches EOF or is closed.

`RecordModeOnce` is the default. It records when the cassette does not exist.
It only replays when the cassette already exists.

| Mode | Behavior |
|---|---|
| `RecordModeNone` | Replay only. Return `ErrNoMatch` for a miss. |
| `RecordModeOnce` | Record a new cassette or replay an existing one. |
| `RecordModeNewEpisodes` | Replay existing interactions and record misses. |
| `RecordModeAll` | Record every request and replace existing interactions. |
| `RecordModeRewrite` | Remove the cassette first, then record every request. |

Use a `.toml` path to store HTTP cassettes as TOML. Other extensions use YAML.

## Configure request matching

```go
transport := cassetter.NewTransport(
    http.DefaultTransport,
    cassetter.WithPath("testdata/cassettes/chat.yaml"),
    cassetter.WithMatchers(
        cassetter.MatcherMethod,
        cassetter.MatcherURI,
        cassetter.MatcherJSONBody,
    ),
    cassetter.WithIgnoredJSONPaths("request_id", "metadata.timestamp"),
)
```

Available matchers are `method`, `uri`, `headers`, `body`, and `json_body`.
The headers matcher requires every recorded header to have the same values in the incoming request.
Use `WithURINormalizer` when environment-specific URI segments should compare as the same resource.

## Expire old cassettes

```go
package main

import (
    "net/http"
    "time"

    "github.com/Kludex/cassetter/go"
)

func main() {
    transport := cassetter.NewTransport(
        http.DefaultTransport,
        cassetter.WithPath("testdata/cassettes/users.yaml"),
        cassetter.WithMaxAge(7*24*time.Hour),
        cassetter.WithExpiryAction(cassetter.ExpiryRerecord),
    )
    _ = transport
}
```

The default expiry action is `ExpiryWarn`. Use `ExpiryFail` to return a
`CassetteExpiredError`, or `ExpiryRerecord` to remove the cassette and start
again. `RecordModeNone` still cannot record after an expired cassette is removed.

## Bypass and transform traffic

```go
package main

import (
    "net/http"

    "github.com/Kludex/cassetter/go"
)

func main() {
    transport := cassetter.NewTransport(
        http.DefaultTransport,
        cassetter.WithPath("testdata/cassettes/users.yaml"),
        cassetter.WithIgnoreLocalhost(),
        cassetter.WithIgnoreHosts("*.googleapis.com"),
        cassetter.WithRequestHook(func(request *http.Request) error {
            request.Header.Del("X-Volatile-ID")
            return nil
        }),
        cassetter.WithResponseHook(func(response *http.Response) error {
            response.Header.Del("X-Request-ID")
            return nil
        }),
    )
    _ = transport
}
```

Bypassed requests go directly to the wrapped transport. The request hook runs
before matching and can change the request sent live. The response hook runs
only for live responses. Return `ErrSkipRecording` from either hook to pass the
exchange through without recording it. Other hook errors fail the request. Hooks
may run concurrently when the transport is shared. A hook that replaces a body
must close the previous body.

Recorded JSON and text bodies are normalized to Unicode NFC before they are
saved.

## Use cassettes in tests

```go
package example_test

import (
    "io"
    "net/http"
    "testing"

    "github.com/Kludex/cassetter/go"
)

func TestUsers(t *testing.T) {
    transport := cassetter.NewTestTransport(
        t,
        http.DefaultTransport,
        cassetter.WithPath("testdata/cassettes/users.yaml"),
    )
    client := &http.Client{Transport: transport}

    response, err := client.Get("https://api.example.com/users")
    if err != nil {
        t.Fatal(err)
    }
    defer response.Body.Close()
    if _, err := io.ReadAll(response.Body); err != nil {
        t.Fatal(err)
    }
}
```

`NewTestTransport` loads the cassette immediately and registers test cleanup.
Cleanup reports failed saves and response bodies that were not fully consumed.
Call `Transport.Initialize` and `Transport.Close` directly when you need the same lifecycle outside a test.

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

## Inspect, diff, scrub, and convert

```bash
go install github.com/Kludex/cassetter/go/cmd/cassetter@latest

cassetter inspect tests/cassettes/openai.yaml
cassetter diff tests/cassettes/openai.yaml tests/cassettes/openai-new.yaml
cassetter scrub tests/cassettes/openai.yaml
cassetter scrub --header x-company-token input.yaml output.yaml
cassetter convert input.yaml output.toml
cassetter convert --to toml tests/cassettes converted-cassettes
```

`cassetter diff` exits with status `1` when it finds a difference. This lets you use it in CI.

`cassetter scrub` rewrites the input atomically when you omit the output path.
It applies the same safe defaults as the HTTP transport. Pass `--force` to
overwrite a separate output file.

`cassetter convert` detects YAML or TOML from each file extension. It filters
secrets by default, including secrets in VCR.py cassettes. Pass `--no-scrub` to
preserve the source values. TOML supports HTTP interactions only.

## Scope

The first release supports YAML and TOML cassettes and HTTP through
`http.RoundTripper`. `Load` accepts structured Cassetter YAML, VCR.py YAML, and
Cassetter TOML. It exposes typed HTTP, gRPC, and WebSocket interactions. YAML
rewrites preserve unrecognized top-level protocol sections. gRPC interceptors
and WebSocket recording are planned.
