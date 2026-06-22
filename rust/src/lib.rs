mod body;
mod cassette;
mod matching;
mod protocol;
mod security;

use pyo3::prelude::*;

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // HTTP protocol types
    m.add_class::<protocol::http::Body>()?;
    m.add_class::<protocol::http::HttpRequest>()?;
    m.add_class::<protocol::http::HttpResponse>()?;
    m.add_class::<protocol::http::HttpInteraction>()?;

    // gRPC protocol types
    m.add_class::<protocol::grpc::GrpcRequest>()?;
    m.add_class::<protocol::grpc::GrpcResponse>()?;
    m.add_class::<protocol::grpc::GrpcInteraction>()?;

    // WebSocket protocol types
    m.add_class::<protocol::ws::WsFrame>()?;
    m.add_class::<protocol::ws::WsInteraction>()?;

    // Cassette
    m.add_class::<cassette::Cassette>()?;

    // Matching
    m.add_class::<matching::config::MatchConfig>()?;
    m.add_function(wrap_pyfunction!(matching::find_match, m)?)?;
    m.add_function(wrap_pyfunction!(matching::find_grpc_match, m)?)?;
    m.add_function(wrap_pyfunction!(matching::find_ws_match, m)?)?;

    // Security
    m.add_class::<security::SecurityConfig>()?;
    m.add_function(wrap_pyfunction!(security::scrub_interaction, m)?)?;
    m.add_function(wrap_pyfunction!(security::scrub_ws_interaction, m)?)?;

    // Body processing
    m.add_function(wrap_pyfunction!(body::process_body, m)?)?;

    Ok(())
}
