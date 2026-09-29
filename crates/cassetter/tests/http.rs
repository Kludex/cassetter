use cassetter::{Error, RecordMode, Recorder};
use reqwest::{Method, Request, Url};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

#[tokio::test]
async fn records_and_replays_http_responses_and_errors_offline() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("google-http.yaml");
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        for (status, body) in [
            ("200 OK", r#"{"name":"queues/one"}"#),
            ("503 Unavailable", r#"{"error":"retry"}"#),
        ] {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = vec![0; 4096];
            let _ = stream.read(&mut request).await.unwrap();
            let response = format!(
                "HTTP/1.1 {status}\r\ncontent-type: application/json\r\nx-request-id: recorded\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                body.len()
            );
            stream.write_all(response.as_bytes()).await.unwrap();
        }
    });

    let recorder = Recorder::builder(&path)
        .record_mode(RecordMode::All)
        .match_on(["method", "uri", "headers", "json_body"])
        .unwrap()
        .build()
        .unwrap();
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
    let url = Url::parse(&format!("http://{address}/v2/projects/test/queues")).unwrap();

    let first = request(url.clone(), "one", "secret");
    let response = client.execute(first).await.unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.bytes().await.unwrap(), r#"{"name":"queues/one"}"#);

    let second = request(url.clone(), "error", "secret");
    let response = client.execute(second).await.unwrap();
    assert_eq!(response.status(), 503);
    assert_eq!(response.bytes().await.unwrap(), r#"{"error":"retry"}"#);
    recorder.finish().await.unwrap();
    server.await.unwrap();

    let cassette = std::fs::read_to_string(&path).unwrap();
    assert!(cassette.contains("x-request-id"));
    assert!(!cassette.contains("Bearer secret"));
    assert!(!cassette.contains("google-api-key"));

    let replay = Recorder::builder(&path)
        .record_mode(RecordMode::None)
        .match_on(["method", "uri", "headers", "json_body"])
        .unwrap()
        .build()
        .unwrap();
    let offline = cassetter::reqwest::Client::new(reqwest::Client::new(), replay.clone());
    assert_eq!(
        offline
            .execute(request(url.clone(), "one", "secret"))
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        offline
            .execute(request(url.clone(), "error", "secret"))
            .await
            .unwrap()
            .status(),
        503
    );

    let error = offline
        .execute(request(url, "different", "secret"))
        .await
        .unwrap_err();
    assert!(matches!(
        error,
        Error::NoMatch {
            protocol: "HTTP",
            ..
        }
    ));
    replay.finish().await.unwrap();
}

#[tokio::test]
async fn skips_opaque_headers_that_cassettes_cannot_represent() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("opaque.yaml");
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut request = vec![0; 4096];
        let _ = stream.read(&mut request).await.unwrap();
        let mut response = b"HTTP/1.1 200 OK\r\nx-opaque: ".to_vec();
        response.extend_from_slice(&[0xff]);
        response.extend_from_slice(b"\r\ncontent-length: 2\r\nconnection: close\r\n\r\nok");
        stream.write_all(&response).await.unwrap();
    });
    let url = Url::parse(&format!("http://{address}/opaque")).unwrap();
    let recorder = Recorder::builder(&path)
        .record_mode(RecordMode::All)
        .build()
        .unwrap();
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
    assert_eq!(
        client
            .execute(Request::new(Method::GET, url.clone()))
            .await
            .unwrap()
            .text()
            .await
            .unwrap(),
        "ok"
    );
    recorder.finish().await.unwrap();
    server.await.unwrap();
    assert!(!std::fs::read_to_string(&path).unwrap().contains("x-opaque"));

    let replay = Recorder::builder(path)
        .record_mode(RecordMode::None)
        .build()
        .unwrap();
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), replay.clone());
    assert_eq!(
        client
            .execute(Request::new(Method::GET, url))
            .await
            .unwrap()
            .text()
            .await
            .unwrap(),
        "ok"
    );
    replay.finish().await.unwrap();
}

#[tokio::test]
async fn preserves_content_length_for_bodyless_responses() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("head.yaml");
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut request = vec![0; 4096];
        let _ = stream.read(&mut request).await.unwrap();
        stream
            .write_all(b"HTTP/1.1 200 OK\r\ncontent-length: 123\r\nconnection: close\r\n\r\n")
            .await
            .unwrap();
    });
    let url = Url::parse(&format!("http://{address}/head")).unwrap();
    let recorder = Recorder::builder(&path)
        .record_mode(RecordMode::All)
        .build()
        .unwrap();
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
    let response = client
        .execute(Request::new(Method::HEAD, url.clone()))
        .await
        .unwrap();
    assert_eq!(response.headers()["content-length"], "123");
    recorder.finish().await.unwrap();
    server.await.unwrap();

    let replay = Recorder::builder(path)
        .record_mode(RecordMode::None)
        .build()
        .unwrap();
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), replay.clone());
    let response = client
        .execute(Request::new(Method::HEAD, url))
        .await
        .unwrap();
    assert_eq!(response.headers()["content-length"], "123");
    assert!(response.bytes().await.unwrap().is_empty());
    replay.finish().await.unwrap();
}

#[tokio::test]
async fn concurrent_recorders_keep_cassettes_isolated() {
    let directory = tempfile::tempdir().unwrap();
    let (first_url, first_server) = one_response_server("first").await;
    let (second_url, second_server) = one_response_server("second").await;
    let first_path = directory.path().join("first.yaml");
    let second_path = directory.path().join("second.yaml");
    let first_recorder = Recorder::builder(&first_path)
        .record_mode(RecordMode::All)
        .build()
        .unwrap();
    let second_recorder = Recorder::builder(&second_path)
        .record_mode(RecordMode::All)
        .build()
        .unwrap();
    let first = cassetter::reqwest::Client::new(reqwest::Client::new(), first_recorder.clone());
    let second = cassetter::reqwest::Client::new(reqwest::Client::new(), second_recorder.clone());

    let (first_response, second_response) = tokio::join!(
        first.execute(Request::new(Method::GET, first_url)),
        second.execute(Request::new(Method::GET, second_url)),
    );
    assert_eq!(first_response.unwrap().text().await.unwrap(), "first");
    assert_eq!(second_response.unwrap().text().await.unwrap(), "second");
    first_recorder.finish().await.unwrap();
    second_recorder.finish().await.unwrap();
    first_server.await.unwrap();
    second_server.await.unwrap();

    let first_cassette = std::fs::read_to_string(first_path).unwrap();
    let second_cassette = std::fs::read_to_string(second_path).unwrap();
    assert!(first_cassette.contains("first"));
    assert!(!first_cassette.contains("second"));
    assert!(second_cassette.contains("second"));
    assert!(!second_cassette.contains("first"));
}

#[tokio::test]
async fn cassette_is_written_only_on_finish() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("deferred.yaml");
    let (url, server) = one_response_server("body").await;
    let recorder = Recorder::builder(&path)
        .record_mode(RecordMode::All)
        .build()
        .unwrap();
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
    assert_eq!(
        client
            .execute(Request::new(Method::GET, url))
            .await
            .unwrap()
            .text()
            .await
            .unwrap(),
        "body"
    );
    assert!(!path.exists());
    recorder.finish().await.unwrap();
    server.await.unwrap();
    assert!(std::fs::read_to_string(path).unwrap().contains("body"));
}

#[tokio::test]
async fn finalization_reports_a_save_error() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cassette.yaml");
    std::fs::create_dir(&path).unwrap();
    let (url, server) = one_response_server("response").await;
    let recorder = Recorder::builder(path)
        .record_mode(RecordMode::All)
        .build()
        .unwrap();
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
    let response = client
        .execute(Request::new(Method::GET, url))
        .await
        .unwrap();
    assert_eq!(response.text().await.unwrap(), "response");
    let error = recorder.finish().await.unwrap_err();
    assert!(matches!(error, Error::Recording(_)));
    let error = recorder.finish().await.unwrap_err();
    assert!(matches!(error, Error::Recording(_)));
    server.await.unwrap();
}

#[tokio::test]
async fn finalization_reports_a_cancelled_recording() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cancelled.yaml");
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (accepted_tx, accepted_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        accepted_tx.send(()).unwrap();
        let _ = release_rx.await;
        drop(stream);
    });
    let recorder = Recorder::builder(path)
        .record_mode(RecordMode::All)
        .build()
        .unwrap();
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
    let task = tokio::spawn(async move {
        client
            .execute(Request::new(
                Method::GET,
                Url::parse(&format!("http://{address}/hang")).unwrap(),
            ))
            .await
    });
    accepted_rx.await.unwrap();
    task.abort();
    let _ = task.await;

    let error = recorder.finish().await.unwrap_err();
    assert!(
        error.to_string().contains("incomplete cassette recording"),
        "{error}"
    );
    release_tx.send(()).unwrap();
    server.await.unwrap();
}

async fn one_response_server(body: &'static str) -> (Url, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut request = vec![0; 4096];
        let _ = stream.read(&mut request).await.unwrap();
        let response = format!(
            "HTTP/1.1 200 OK\r\ncontent-type: text/plain\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
            body.len()
        );
        stream.write_all(response.as_bytes()).await.unwrap();
    });
    (
        Url::parse(&format!("http://{address}/value")).unwrap(),
        server,
    )
}

fn request(url: Url, value: &str, credential: &str) -> Request {
    let mut request = Request::new(Method::POST, url);
    request
        .headers_mut()
        .insert("content-type", "application/json".parse().unwrap());
    request.headers_mut().insert(
        "authorization",
        format!("Bearer {credential}").parse().unwrap(),
    );
    request
        .headers_mut()
        .insert("x-goog-api-key", "google-api-key".parse().unwrap());
    let body = format!(r#"{{ "name": "{value}" }}"#);
    request
        .headers_mut()
        .insert("content-length", body.len().into());
    *request.body_mut() = Some(reqwest::Body::from(body));
    request
}
