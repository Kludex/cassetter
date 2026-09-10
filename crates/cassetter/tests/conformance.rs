use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use cassetter::{Error, RecordMode, Recorder};
use cassetter_core::body::compression::DEFAULT_MAX_DECOMPRESSED;
use cassetter_core::body::process_body;
use cassetter_core::cassette::Cassette;
use cassetter_core::interop::{body_from_json, body_to_json, security_config_from_json};
use cassetter_core::matching::config::MatchConfig;
use cassetter_core::protocol::http::{BodyContent, HttpRequest};
use cassetter_core::security::{scrub_grpc_interaction, scrub_interaction, scrub_ws_interaction};
use reqwest::{Method, Request, Url};
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

#[test]
fn shared_format_fixtures_parse_and_round_trip() {
    let root = fixtures("format");
    let cases: Vec<FormatCase> = read_json(&root.join("cases.json"));
    for case in cases {
        let path = root.join(&case.cassette);
        let cassette = Cassette::load(path.to_str().unwrap()).unwrap_or_else(|error| {
            panic!("{} failed to load: {error}", case.name);
        });
        let expected: Value = read_json(&root.join(&case.expected));
        assert_eq!(canonical(&cassette), expected, "{}", case.name);

        let directory = tempfile::tempdir().unwrap();
        let round_trip = directory.path().join(&case.cassette);
        cassette
            .save(round_trip.to_str().unwrap(), None, None)
            .unwrap();
        let loaded = Cassette::load(round_trip.to_str().unwrap()).unwrap();
        assert_eq!(canonical(&loaded), expected, "{} round trip", case.name);
    }
}

#[test]
fn shared_invalid_format_fixtures_are_rejected() {
    let root = fixtures("format/invalid");
    let cases: Vec<InvalidCase> = read_json(&root.join("cases.json"));
    for case in cases {
        let path = root.join(&case.cassette);
        assert!(
            Cassette::load(path.to_str().unwrap()).is_err(),
            "{}",
            case.name
        );
    }
}

#[test]
fn shared_matching_fixtures_have_the_expected_results() {
    let root = fixtures("matching");
    let source = Cassette::load(root.join("cassette.yaml").to_str().unwrap()).unwrap();
    let cases: Vec<MatchingCase> = read_json(&root.join("cases.json"));
    for case in cases {
        let mut cassette = source.clone();
        let config = MatchConfig::new(case.match_on, case.ignore_json_paths).unwrap();
        let statuses = case
            .requests
            .iter()
            .map(|request| {
                let request = HttpRequest::new(
                    request["method"].as_str().unwrap().to_string(),
                    request["uri"].as_str().unwrap().to_string(),
                    request.get("headers").map(headers),
                    request.get("body").map(body_from_json),
                );
                cassette
                    .take_match(&request, &config)
                    .map(|(_, interaction)| interaction.response.status)
            })
            .collect::<Vec<_>>();
        assert_eq!(statuses, case.expected_statuses, "{}", case.name);
    }
}

#[test]
fn shared_filtering_fixtures_have_the_expected_results() {
    let root = fixtures("filtering");
    let source = Cassette::load(root.join("input.yaml").to_str().unwrap()).unwrap();
    let cases: Vec<Value> = read_json(&root.join("cases.json"));
    for case in cases {
        let config = security_config_from_json(&case).unwrap();
        let mut cassette = source.clone();
        cassette.set_interactions(
            cassette
                .interactions
                .iter()
                .map(|interaction| scrub_interaction(interaction, &config))
                .collect(),
        );
        cassette.set_grpc_interactions(
            cassette
                .grpc_interactions
                .iter()
                .map(|interaction| scrub_grpc_interaction(interaction, &config))
                .collect(),
        );
        cassette.set_ws_interactions(
            cassette
                .ws_interactions
                .iter()
                .map(|interaction| scrub_ws_interaction(interaction, &config))
                .collect(),
        );
        let expected: Value = read_json(&root.join(case["expected"].as_str().unwrap()));
        assert_eq!(canonical(&cassette), expected, "{}", case["name"]);
    }
}

#[test]
fn shared_body_processing_fixtures_have_the_expected_results() {
    let root = fixtures("body-processing");
    let cassette = Cassette::load(root.join("cases.yaml").to_str().unwrap()).unwrap();
    let expected: BTreeMap<String, Value> = read_json(&root.join("expected.json"));
    for interaction in cassette.interactions {
        let raw = match interaction.response.body.inner {
            BodyContent::None => Vec::new(),
            BodyContent::Binary(value) => value,
            BodyContent::Text(value) => value.into_bytes(),
            BodyContent::Json(value) => serde_json::to_vec(&value).unwrap(),
        };
        let processed = process_body(
            raw,
            first_header(&interaction.response.headers, "content-type"),
            first_header(&interaction.response.headers, "content-encoding"),
            DEFAULT_MAX_DECOMPRESSED,
        )
        .unwrap();
        assert_eq!(
            body_to_json(&processed),
            expected[&interaction.request.uri],
            "{}",
            interaction.request.uri
        );
    }
}

#[tokio::test]
async fn shared_record_mode_fixtures_have_the_expected_results() {
    let root = fixtures("record-modes");
    let cases: Vec<RecordModeCase> = read_json(&root.join("cases.json"));
    for case in cases {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("cassette.yaml");
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let base = format!("http://{address}");
        if case.existing {
            let mut cassette =
                Cassette::load(root.join("existing.yaml").to_str().unwrap()).unwrap();
            cassette.interactions[0].request.uri = format!("{base}/recorded");
            cassette.save(path.to_str().unwrap(), None, None).unwrap();
        }
        let expected_calls = case.expected_base_calls;
        let server = tokio::spawn(async move {
            for _ in 0..expected_calls {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut request = vec![0; 4096];
                let _ = stream.read(&mut request).await.unwrap();
                stream
                    .write_all(
                        b"HTTP/1.1 299 Recorded\r\ncontent-length: 0\r\nconnection: close\r\n\r\n",
                    )
                    .await
                    .unwrap();
            }
        });
        let recorder = Recorder::builder(&path)
            .record_mode(record_mode(&case.mode))
            .build()
            .unwrap();
        let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
        for (uri, outcome) in case.requests.iter().zip(&case.expected_outcomes) {
            let url = uri.replace("https://example.com", &base);
            let result = client
                .execute(Request::new(Method::GET, Url::parse(&url).unwrap()))
                .await;
            match outcome.as_str() {
                "replay" => {
                    let expected = if uri.ends_with("/recorded") { 201 } else { 299 };
                    assert_eq!(result.unwrap().status(), expected, "{}", case.name);
                }
                "live" => assert_eq!(result.unwrap().status(), 299, "{}", case.name),
                "no_match" => assert!(
                    matches!(result, Err(Error::NoMatch { .. })),
                    "{}",
                    case.name
                ),
                other => panic!("unknown outcome {other}"),
            }
        }
        recorder.finish().await.unwrap();
        server.await.unwrap();

        match case.expected_file {
            None => assert!(!path.exists(), "{}", case.name),
            Some(expected) => {
                let cassette = Cassette::load(path.to_str().unwrap()).unwrap();
                let actual = cassette
                    .interactions
                    .iter()
                    .map(|interaction| {
                        json!({
                            "uri": interaction.request.uri.replace(&base, "https://example.com"),
                            "status": interaction.response.status,
                        })
                    })
                    .collect::<Vec<_>>();
                assert_eq!(actual, expected, "{}", case.name);
            }
        }
    }
}

#[derive(Deserialize)]
struct FormatCase {
    name: String,
    cassette: String,
    expected: String,
}

#[derive(Deserialize)]
struct InvalidCase {
    name: String,
    cassette: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RecordModeCase {
    name: String,
    mode: String,
    existing: bool,
    requests: Vec<String>,
    expected_outcomes: Vec<String>,
    expected_base_calls: usize,
    expected_file: Option<Vec<Value>>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct MatchingCase {
    name: String,
    #[serde(default)]
    match_on: Option<Vec<String>>,
    #[serde(default)]
    ignore_json_paths: Option<Vec<String>>,
    requests: Vec<Value>,
    expected_statuses: Vec<Option<u16>>,
}

fn record_mode(mode: &str) -> RecordMode {
    match mode {
        "none" => RecordMode::None,
        "once" => RecordMode::Once,
        "new_episodes" => RecordMode::NewEpisodes,
        "all" => RecordMode::All,
        "rewrite" => RecordMode::Rewrite,
        other => panic!("unknown record mode {other}"),
    }
}

fn fixtures(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../conformance")
        .join(name)
}

fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> T {
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

fn headers(value: &Value) -> std::collections::HashMap<String, Vec<String>> {
    serde_json::from_value(value.clone()).unwrap()
}

fn canonical(cassette: &Cassette) -> Value {
    json!({
        "version": cassette.version,
        "http": cassette.interactions.iter().map(|interaction| json!({
            "method": interaction.request.method,
            "uri": interaction.request.uri,
            "requestHeaders": sorted_headers(&interaction.request.headers),
            "requestBody": body_to_json(&interaction.request.body),
            "status": interaction.response.status,
            "responseHeaders": sorted_headers(&interaction.response.headers),
            "responseBody": body_to_json(&interaction.response.body),
            "recordedAt": interaction.recorded_at,
        })).collect::<Vec<_>>(),
        "grpc": cassette.grpc_interactions.iter().map(|interaction| json!({
            "method": interaction.request.method,
            "metadata": sorted_headers(&interaction.request.metadata),
            "requestBody": body_to_json(&interaction.request.body),
            "statusCode": interaction.response.status_code,
            "statusMessage": interaction.response.status_message,
            "responseMetadata": sorted_headers(&interaction.response.metadata),
            "responseBody": body_to_json(&interaction.response.body),
            "jsonDebug": interaction.json_debug,
            "recordedAt": interaction.recorded_at,
        })).collect::<Vec<_>>(),
        "ws": cassette.ws_interactions.iter().map(|interaction| json!({
            "uri": interaction.uri,
            "headers": sorted_headers(&interaction.headers),
            "frames": interaction.frames.iter().map(|frame| json!({
                "direction": frame.direction,
                "frameType": frame.frame_type,
                "body": body_to_json(&frame.body),
                "offsetMs": frame.offset_ms,
            })).collect::<Vec<_>>(),
            "recordedAt": interaction.recorded_at,
        })).collect::<Vec<_>>(),
    })
}

fn sorted_headers(
    headers: &std::collections::HashMap<String, Vec<String>>,
) -> BTreeMap<&str, &Vec<String>> {
    headers
        .iter()
        .map(|(name, values)| (name.as_str(), values))
        .collect()
}

fn first_header<'a>(
    headers: &'a std::collections::HashMap<String, Vec<String>>,
    name: &str,
) -> Option<&'a str> {
    headers
        .iter()
        .find(|(candidate, _)| candidate.eq_ignore_ascii_case(name))
        .and_then(|(_, values)| values.first())
        .map(String::as_str)
}
