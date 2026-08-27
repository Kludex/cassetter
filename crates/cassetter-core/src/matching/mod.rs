pub mod config;
pub mod matchers;

use crate::cassette::index::CassetteIndex;
use crate::protocol::grpc::GrpcInteraction;
use crate::protocol::http::{HttpInteraction, HttpRequest};
use crate::protocol::ws::WsInteraction;
use config::MatchConfig;

/// Find the index of a matching interaction.
///
/// Prefers unplayed interactions; falls back to already-played ones. `index`
/// is an optional prebuilt method+URI index; when absent every interaction is
/// a candidate.
pub fn find_match_index(
    request: &HttpRequest,
    interactions: &[HttpInteraction],
    played: &[bool],
    config: &MatchConfig,
    index: Option<&CassetteIndex>,
) -> Option<usize> {
    match index {
        Some(index) => scan(
            index.lookup(&request.method, &request.uri).iter().copied(),
            request,
            interactions,
            played,
            config,
        ),
        None => scan(0..interactions.len(), request, interactions, played, config),
    }
}

fn scan<I: Iterator<Item = usize>>(
    candidates: I,
    request: &HttpRequest,
    interactions: &[HttpInteraction],
    played: &[bool],
    config: &MatchConfig,
) -> Option<usize> {
    let mut fallback = None;
    for idx in candidates {
        let Some(interaction) = interactions.get(idx) else {
            continue;
        };
        if !matches_all(request, &interaction.request, config) {
            continue;
        }
        if !played.get(idx).copied().unwrap_or(false) {
            return Some(idx);
        }
        if fallback.is_none() {
            fallback = Some(idx);
        }
    }
    fallback
}

/// Find a matching interaction for the given request.
///
/// Prefers unplayed interactions; falls back to already-played ones.
/// Returns (index, interaction) if found.
///
/// Prefer [`crate::cassette::Cassette::take_match`], which matches against the
/// interactions already held in Rust instead of marshalling them across a
/// binding boundary on every call.
pub fn find_match(
    request: &HttpRequest,
    interactions: &[HttpInteraction],
    played: &[bool],
    config: &MatchConfig,
) -> Option<(usize, HttpInteraction)> {
    let index = config
        .uses_method_uri_index()
        .then(|| CassetteIndex::build(interactions));
    let idx = find_match_index(request, interactions, played, config, index.as_ref())?;
    Some((idx, interactions[idx].clone()))
}

/// Find a matching gRPC interaction by method string.
/// Prefers unplayed interactions; falls back to already-played ones.
pub fn find_grpc_match(
    method: &str,
    interactions: &[GrpcInteraction],
    played: &[bool],
) -> Option<(usize, GrpcInteraction)> {
    let idx = find_grpc_match_index(method, interactions, played)?;
    Some((idx, interactions[idx].clone()))
}

pub fn find_grpc_match_index(
    method: &str,
    interactions: &[GrpcInteraction],
    played: &[bool],
) -> Option<usize> {
    let mut fallback = None;
    for (idx, interaction) in interactions.iter().enumerate() {
        if interaction.request.method != method {
            continue;
        }
        if !played.get(idx).copied().unwrap_or(false) {
            return Some(idx);
        }
        if fallback.is_none() {
            fallback = Some(idx);
        }
    }
    fallback
}

/// Find a matching WebSocket interaction by URI.
/// Prefers unplayed interactions; falls back to already-played ones.
pub fn find_ws_match(
    uri: &str,
    interactions: &[WsInteraction],
    played: &[bool],
) -> Option<(usize, WsInteraction)> {
    let idx = find_ws_match_index(uri, interactions, played)?;
    Some((idx, interactions[idx].clone()))
}

pub fn find_ws_match_index(
    uri: &str,
    interactions: &[WsInteraction],
    played: &[bool],
) -> Option<usize> {
    let mut fallback = None;
    for (idx, interaction) in interactions.iter().enumerate() {
        if interaction.uri != uri {
            continue;
        }
        if !played.get(idx).copied().unwrap_or(false) {
            return Some(idx);
        }
        if fallback.is_none() {
            fallback = Some(idx);
        }
    }
    fallback
}

fn matches_all(incoming: &HttpRequest, recorded: &HttpRequest, config: &MatchConfig) -> bool {
    for field in &config.match_on {
        let matched = match field.as_str() {
            "method" => matchers::match_method(incoming, recorded),
            "uri" => matchers::match_uri(incoming, recorded),
            "headers" => matchers::match_headers(incoming, recorded),
            "body" => matchers::match_body(incoming, recorded),
            "json_body" => matchers::match_json_body(incoming, recorded, &config.ignore_json_paths),
            // Unreachable via the validated constructor and setter. Failing
            // closed keeps an unknown matcher from silently matching every
            // request and serving the wrong recorded response.
            _ => false,
        };
        if !matched {
            return false;
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::http::{Body, HttpResponse};

    fn interaction(method: &str, uri: &str) -> HttpInteraction {
        HttpInteraction {
            request: HttpRequest {
                method: method.to_string(),
                uri: uri.to_string(),
                headers: Default::default(),
                body: Body::none(),
            },
            response: HttpResponse {
                status: 200,
                headers: Default::default(),
                body: Body::none(),
            },
            recorded_at: "2026-01-01T00:00:00Z".to_string(),
        }
    }

    fn request(method: &str, uri: &str) -> HttpRequest {
        HttpRequest {
            method: method.to_string(),
            uri: uri.to_string(),
            headers: Default::default(),
            body: Body::none(),
        }
    }

    #[test]
    fn test_unknown_matcher_fails_closed() {
        let config = MatchConfig {
            match_on: vec!["bogus".to_string()],
            ignore_json_paths: Vec::new(),
        };
        let interactions = vec![interaction("GET", "/a")];
        assert!(find_match(
            &request("DELETE", "/nowhere"),
            &interactions,
            &[false],
            &config
        )
        .is_none());
    }

    #[test]
    fn test_method_uri_match_still_works() {
        let config = MatchConfig {
            match_on: vec!["method".to_string(), "uri".to_string()],
            ignore_json_paths: Vec::new(),
        };
        let interactions = vec![interaction("GET", "/a"), interaction("POST", "/b")];
        let hit = find_match(
            &request("POST", "/b"),
            &interactions,
            &[false, false],
            &config,
        );
        assert_eq!(hit.map(|(idx, _)| idx), Some(1));
    }

    #[test]
    fn test_unknown_matcher_is_rejected_at_construction() {
        assert!(MatchConfig::new(Some(vec!["bogus".to_string()]), None).is_err());
        assert!(MatchConfig::new(Some(vec![]), None).is_err());
    }
}
