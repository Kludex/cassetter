mod body;
mod cassette;
mod matching;
mod protocol;
mod security;

use pyo3::prelude::*;

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Protocol types
    m.add_class::<protocol::http::Body>()?;
    m.add_class::<protocol::http::HttpRequest>()?;
    m.add_class::<protocol::http::HttpResponse>()?;
    m.add_class::<protocol::http::HttpInteraction>()?;

    // Cassette
    m.add_class::<cassette::Cassette>()?;

    // Matching
    m.add_class::<matching::config::MatchConfig>()?;
    m.add_function(wrap_pyfunction!(matching::find_match, m)?)?;

    // Security
    m.add_class::<security::SecurityConfig>()?;
    m.add_function(wrap_pyfunction!(security::scrub_interaction, m)?)?;

    // Body processing
    m.add_function(wrap_pyfunction!(body::process_body, m)?)?;

    Ok(())
}
