use cassetter::{RecordMode, Recorder};
use tonic::transport::Channel;
use tonic_health::pb::health_client::HealthClient;
use tonic_health::pb::HealthCheckRequest;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let recorder = Recorder::builder("tests/cassettes/health.yaml")
        .record_mode(RecordMode::Once)
        .build()?;
    let channel = Channel::from_static("https://api.example.com").connect_lazy();
    let service = cassetter::tonic::GrpcService::new(channel, recorder.clone());
    let mut client = HealthClient::new(service);

    let _response = client.check(HealthCheckRequest::default()).await?;
    recorder.finish().await?;
    Ok(())
}
