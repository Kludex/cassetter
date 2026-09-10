use std::collections::VecDeque;
use std::convert::Infallible;
use std::future::{ready, Ready};
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll};

use bytes::Bytes;
use cassetter::{RecordMode, Recorder};
use googleapis_tonic_google_cloud_tasks_v2::google::cloud::tasks::v2::cloud_tasks_client::CloudTasksClient;
use googleapis_tonic_google_cloud_tasks_v2::google::cloud::tasks::v2::{GetQueueRequest, Queue};
use http::{HeaderMap, Request, Response};
use http_body::{Body, Frame};
use prost::Message;
use tower_service::Service;

#[tokio::test]
async fn google_cloud_tasks_records_and_replays_successes_and_errors() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cloud-tasks.yaml");
    let live_calls = Arc::new(AtomicUsize::new(0));
    let recorder = Recorder::builder(&path)
        .record_mode(RecordMode::All)
        .build()
        .unwrap();
    let transport = GoogleTransport {
        calls: live_calls.clone(),
    };
    let mut client = CloudTasksClient::new(cassetter::tonic::GrpcService::new(
        transport,
        recorder.clone(),
    ));

    let response = client.get_queue(request("queues/one")).await.unwrap();
    assert!(response.metadata().get("x-server-header").is_some());
    assert_eq!(response.into_inner().name, "queues/one");
    let error = client
        .get_queue(request("queues/missing"))
        .await
        .unwrap_err();
    assert_eq!(error.code(), tonic::Code::NotFound);
    assert_eq!(error.message(), "queue missing");
    let error = client
        .get_queue(request("queues/proxy-error"))
        .await
        .unwrap_err();
    assert_eq!(error.code(), tonic::Code::Unavailable);
    assert!(error.message().contains("HTTP status code 503"));
    assert_eq!(live_calls.load(Ordering::SeqCst), 3);
    recorder.finish().await.unwrap();

    let cassette = std::fs::read_to_string(&path).unwrap();
    assert!(cassette.contains("/google.cloud.tasks.v2.CloudTasks/GetQueue"));
    assert!(cassette.contains("status_code: 5"));
    assert!(cassette.contains("status_code: 14"));
    assert!(cassette.contains("x-server-header"));
    assert!(cassette.contains("x-server-trailer"));
    assert!(!cassette.contains("Bearer secret"));
    assert!(!cassette.contains("google-api-key"));

    let offline_calls = Arc::new(AtomicUsize::new(0));
    let replay = Recorder::builder(&path)
        .record_mode(RecordMode::None)
        .build()
        .unwrap();
    let mut client = CloudTasksClient::new(cassetter::tonic::GrpcService::new(
        OfflineTransport {
            calls: offline_calls.clone(),
        },
        replay.clone(),
    ));

    let response = client.get_queue(request("queues/one")).await.unwrap();
    assert!(response.metadata().get("x-server-header").is_some());
    assert_eq!(response.into_inner().name, "queues/one");
    let error = client
        .get_queue(request("queues/missing"))
        .await
        .unwrap_err();
    assert_eq!(error.code(), tonic::Code::NotFound);
    assert_eq!(error.message(), "queue missing");
    assert!(error.metadata().get("x-server-trailer").is_some());
    let error = client
        .get_queue(request("queues/proxy-error"))
        .await
        .unwrap_err();
    assert_eq!(error.code(), tonic::Code::Unavailable);
    assert!(error.message().contains("HTTP status code 503"));

    let mismatch = client.get_queue(request("queues/other")).await.unwrap_err();
    assert!(mismatch
        .message()
        .contains("no matching gRPC cassette interaction"));
    assert_eq!(offline_calls.load(Ordering::SeqCst), 0);
    replay.finish().await.unwrap();
}

fn request(name: &str) -> tonic::Request<GetQueueRequest> {
    let mut request = tonic::Request::new(GetQueueRequest {
        name: name.to_string(),
    });
    request
        .metadata_mut()
        .insert("authorization", "Bearer secret".parse().unwrap());
    request
        .metadata_mut()
        .insert("x-goog-api-key", "google-api-key".parse().unwrap());
    request
}

#[derive(Clone)]
struct GoogleTransport {
    calls: Arc<AtomicUsize>,
}

impl Service<Request<tonic::body::Body>> for GoogleTransport {
    type Response = Response<tonic::body::Body>;
    type Error = Infallible;
    type Future = Ready<Result<Self::Response, Self::Error>>;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, _request: Request<tonic::body::Body>) -> Self::Future {
        let call = self.calls.fetch_add(1, Ordering::SeqCst);
        match call {
            0 => {
                let payload = Queue {
                    name: "queues/one".to_string(),
                    ..Queue::default()
                }
                .encode_to_vec();
                ready(Ok(grpc_response(payload, 0, "", true)))
            }
            1 => ready(Ok(grpc_response(Vec::new(), 5, "queue%20missing", true))),
            _ => ready(Ok(http_error_response())),
        }
    }
}

#[derive(Clone)]
struct OfflineTransport {
    calls: Arc<AtomicUsize>,
}

impl Service<Request<tonic::body::Body>> for OfflineTransport {
    type Response = Response<tonic::body::Body>;
    type Error = Infallible;
    type Future = Ready<Result<Self::Response, Self::Error>>;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, _request: Request<tonic::body::Body>) -> Self::Future {
        self.calls.fetch_add(1, Ordering::SeqCst);
        panic!("offline replay reached the live Google transport")
    }
}

fn http_error_response() -> Response<tonic::body::Body> {
    Response::builder()
        .status(503)
        .body(tonic::body::Body::empty())
        .unwrap()
}

fn grpc_response(
    payload: Vec<u8>,
    status: u32,
    message: &str,
    with_metadata: bool,
) -> Response<tonic::body::Body> {
    let mut framed = Vec::new();
    if !payload.is_empty() {
        framed.push(0);
        framed.extend_from_slice(&(payload.len() as u32).to_be_bytes());
        framed.extend_from_slice(&payload);
    }
    let mut trailers = HeaderMap::new();
    trailers.insert("grpc-status", status.to_string().parse().unwrap());
    trailers.insert("grpc-message", message.parse().unwrap());
    if with_metadata {
        trailers.insert("x-server-trailer", "present".parse().unwrap());
    }
    Response::builder()
        .status(200)
        .header("content-type", "application/grpc")
        .header("x-server-header", "present")
        .body(tonic::body::Body::new(TestBody::new(
            Bytes::from(framed),
            trailers,
        )))
        .unwrap()
}

struct TestBody {
    frames: VecDeque<Frame<Bytes>>,
}

impl TestBody {
    fn new(data: Bytes, trailers: HeaderMap) -> Self {
        let mut frames = VecDeque::new();
        if !data.is_empty() {
            frames.push_back(Frame::data(data));
        }
        frames.push_back(Frame::trailers(trailers));
        Self { frames }
    }
}

impl Body for TestBody {
    type Data = Bytes;
    type Error = tonic::Status;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        _cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        Poll::Ready(self.frames.pop_front().map(Ok))
    }
}
