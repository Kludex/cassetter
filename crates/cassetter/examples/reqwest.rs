use cassetter::{RecordMode, Recorder};
use reqwest::{Method, Request, Url};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let recorder = Recorder::builder("tests/cassettes/users.yaml")
        .record_mode(RecordMode::Once)
        .build()?;
    let client = cassetter::reqwest::Client::new(reqwest::Client::new(), recorder.clone());
    let request = Request::new(Method::GET, Url::parse("https://api.example.com/users")?);
    let response = client.execute(request).await?;

    let _body = response.text().await?;
    recorder.finish().await?;
    Ok(())
}
