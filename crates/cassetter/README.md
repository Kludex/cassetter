# cassetter for Rust

Record and replay outbound HTTP and unary gRPC calls with the same cassette files as the Python, Node, and Go SDKs.

## Install

```console
cargo add cassetter reqwest
```

Add `tonic` and your generated gRPC client crate when you need gRPC recording. The crate requires Rust 1.88 or newer.

## HTTP with reqwest

```rust,no_run
use cassetter::{RecordMode, Recorder};
use reqwest::{Method, Request, Url};

# async fn run() -> Result<(), Box<dyn std::error::Error>> {
let recorder = Recorder::builder("tests/cassettes/users.yaml")
    .record_mode(RecordMode::Once)
    .build()?;
let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
let request = Request::new(Method::GET, Url::parse("https://api.example.com/users")?);
let response = client.execute(request).await?;
let body = response.bytes().await?;
assert!(!body.is_empty());
recorder.finish().await?;
# Ok(())
# }
```

The wrapper buffers request and response bodies. This makes matching
deterministic and reports body read failures before the call returns. Use
`Client::inner()` to build requests with the wrapped client's configuration.

## gRPC with tonic

```rust,no_run
use cassetter::{RecordMode, Recorder};
use tonic::transport::Channel;
use tonic_health::pb::health_client::HealthClient;

# async fn run() -> Result<(), Box<dyn std::error::Error>> {
let recorder = Recorder::builder("tests/cassettes/health.yaml")
    .record_mode(RecordMode::Once)
    .build()?;
let channel = Channel::from_static("https://api.example.com").connect_lazy();
let service = cassetter::tonic::GrpcService::new(channel, recorder.clone());
let mut client = HealthClient::new(service);
let _ = client
    .check(tonic_health::pb::HealthCheckRequest::default())
    .await?;
recorder.finish().await?;
# Ok(())
# }
```

Pass `GrpcService` to any generated `tonic` client that accepts a transport in
its `new` constructor. Matching uses the full RPC method and exact serialized
protobuf request body. Request metadata is recorded. Response headers and
trailers are merged into the v1 cassette `metadata` field and exposed in both
places during replay. Non-OK gRPC statuses are recorded and replayed.

## Record modes

| Mode | Behavior |
|---|---|
| `RecordMode::None` | Replay only. A missing or mismatched request fails. |
| `RecordMode::Once` | Record if the cassette does not exist, otherwise replay only. |
| `RecordMode::NewEpisodes` | Replay matches and record misses. |
| `RecordMode::All` | Record every request and replace existing interactions. |
| `RecordMode::Rewrite` | Remove the cassette first and record every request. |

Each `Recorder` owns independent playback state. Clone one recorder to share a
cassette safely across concurrent tasks. Build separate recorders when tests
must not consume each other's interactions.

Always call `Recorder::finish`. It saves an empty replacement cassette when
needed and reports persistence failures or calls cancelled while recording.

## Cassette format

YAML is the default. Use a `.toml` path for TOML, or set the suffix for names
that do not already end in `.yaml`, `.yml`, or `.toml`:

```rust,no_run
use cassetter::Recorder;

# async fn run() -> Result<(), Box<dyn std::error::Error>> {
let recorder = Recorder::builder("tests/cassettes/users")
    .cassette_extension("toml")?
    .build()?;
# let _ = recorder;
# Ok(())
# }
```

## Current limits

- HTTP request and response bodies are buffered in memory.
- gRPC supports unary calls only. Client-streaming, server-streaming, and
  bidirectional calls are rejected because the transport requires exactly one
  framed request and response message.
- Compressed gRPC messages are rejected.
- Protobuf payloads are stored as binary bytes. Header filtering applies to
  metadata, but body field filtering cannot inspect binary protobuf data.
  Filter sensitive protobuf fields before they reach the transport. A future
  descriptor-aware API can add safe field-level filtering.
- The v1 cassette format has one response metadata map. Headers and trailers
  are merged when recording and replayed in both locations.
- gRPC interactions require YAML. TOML cassettes support HTTP only.
