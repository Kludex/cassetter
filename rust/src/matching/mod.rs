pub mod config;
pub mod matchers;

use pyo3::prelude::*;

use crate::cassette::index::CassetteIndex;
use crate::protocol::http::{HttpInteraction, HttpRequest};
use config::MatchConfig;

/// Find a matching interaction for the given request.
/// Returns (index, interaction) if found.
#[pyfunction]
pub fn find_match(
    request: &HttpRequest,
    interactions: Vec<HttpInteraction>,
    config: &MatchConfig,
) -> Option<(usize, HttpInteraction)> {
    let match_fields = &config.match_on;

    // Use index for fast method+URI lookup if matching on those fields
    let use_index = match_fields.iter().any(|f| f == "method")
        && match_fields.iter().any(|f| f == "uri");

    let candidates: Vec<usize> = if use_index {
        let index = CassetteIndex::build(&interactions);
        index.lookup(&request.method, &request.uri)
    } else {
        (0..interactions.len()).collect()
    };

    for idx in candidates {
        let interaction = &interactions[idx];
        if matches_all(request, &interaction.request, config) {
            return Some((idx, interaction.clone()));
        }
    }

    None
}

fn matches_all(incoming: &HttpRequest, recorded: &HttpRequest, config: &MatchConfig) -> bool {
    for field in &config.match_on {
        let matched = match field.as_str() {
            "method" => matchers::match_method(incoming, recorded),
            "uri" => matchers::match_uri(incoming, recorded),
            "headers" => matchers::match_headers(incoming, recorded),
            "body" => matchers::match_body(incoming, recorded),
            "json_body" => matchers::match_json_body(incoming, recorded, &config.ignore_json_paths),
            _ => true,
        };
        if !matched {
            return false;
        }
    }
    true
}
