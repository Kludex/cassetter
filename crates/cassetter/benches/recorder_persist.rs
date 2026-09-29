//! Wall-clock cost of recording N HTTP interactions through [`cassetter::Recorder`].
//!
//! This is the path that used to rewrite the cassette file after every
//! response. Run with `cargo bench -p cassetter --bench recorder_persist`.

#![allow(clippy::print_stdout)]

use std::future::Future;
use std::time::{Duration, Instant};

use cassetter::{RecordMode, Recorder};
use reqwest::{Method, Request, Url};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

const ITERATIONS: usize = 8;
const TRIM: usize = 2;
const SCALES: &[usize] = &[10, 100, 1000];

#[tokio::main]
async fn main() {
    println!("cassetter recorder persist");
    println!("iterations: {ITERATIONS} (trimmed mean, drop {TRIM} extremes)");
    println!();
    println!(
        "  {:<8}{:>16}{:>18}",
        "n", "record+finish", "save-once (core)"
    );

    for &n in SCALES {
        let recorder = bench_async(|| record_n(n)).await;
        let core = bench(|| save_once(n));
        println!("  {n:<8}{:>16}{:>18}", fmt(recorder), fmt(core));
    }
}

fn bench(mut run: impl FnMut()) -> Duration {
    let mut times = Vec::with_capacity(ITERATIONS);
    for _ in 0..ITERATIONS {
        let start = Instant::now();
        run();
        times.push(start.elapsed());
    }
    trimmed_mean(&mut times)
}

async fn bench_async<F, Fut>(mut run: F) -> Duration
where
    F: FnMut() -> Fut,
    Fut: Future<Output = ()>,
{
    let mut times = Vec::with_capacity(ITERATIONS);
    for _ in 0..ITERATIONS {
        let start = Instant::now();
        run().await;
        times.push(start.elapsed());
    }
    trimmed_mean(&mut times)
}

fn trimmed_mean(times: &mut [Duration]) -> Duration {
    times.sort();
    let kept = &times[TRIM / 2..times.len() - TRIM / 2];
    kept.iter().sum::<Duration>() / kept.len() as u32
}

fn fmt(duration: Duration) -> String {
    let ms = duration.as_secs_f64() * 1000.0;
    if ms >= 1.0 {
        format!("{ms:.2} ms")
    } else {
        format!("{:.1} us", ms * 1000.0)
    }
}

async fn record_n(n: usize) {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("bench.yaml");
    let (url, server) = n_response_server(n).await;
    let recorder = Recorder::builder(&path)
        .record_mode(RecordMode::All)
        .build()
        .unwrap();
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
    for i in 0..n {
        let request = Request::new(Method::GET, url.join(&format!("/items/{i}")).unwrap());
        client.execute(request).await.unwrap();
    }
    recorder.finish().await.unwrap();
    server.await.unwrap();
}

fn save_once(n: usize) {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("bench.yaml");
    let mut cassette = cassetter_core::cassette::Cassette::new();
    for i in 0..n {
        cassette.add_interaction(interaction(i));
    }
    cassette.save(path.to_str().unwrap(), None, None).unwrap();
}

fn interaction(i: usize) -> cassetter_core::protocol::http::HttpInteraction {
    use cassetter_core::protocol::http::{Body, HttpInteraction, HttpRequest, HttpResponse};

    HttpInteraction::new(
        HttpRequest::new(
            "GET".to_string(),
            format!("https://api.example.com/items/{i}"),
            None,
            Some(Body::json(serde_json::json!({"query": i}))),
        ),
        HttpResponse::new(
            200,
            None,
            Some(Body::json(
                serde_json::json!({"id": i, "name": format!("item-{i}")}),
            )),
        ),
        "2026-01-01T00:00:00Z".to_string(),
    )
}

async fn n_response_server(n: usize) -> (Url, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        for i in 0..n {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = vec![0; 4096];
            let _ = stream.read(&mut request).await.unwrap();
            let body = format!(r#"{{"id":{i}}}"#);
            let response = format!(
                "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                body.len()
            );
            stream.write_all(response.as_bytes()).await.unwrap();
        }
    });
    (Url::parse(&format!("http://{address}")).unwrap(), server)
}
