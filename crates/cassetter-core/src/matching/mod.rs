pub mod config;
pub mod matchers;

use crate::cassette::index::CassetteIndex;
use crate::protocol::grpc::{GrpcInteraction, GrpcRequest};
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
    find_match_index_in(request, interactions, played, config, index, true)
}

/// Like [`find_match_index`], falling back to played interactions only when `allow_played` is set.
pub fn find_match_index_in(
    request: &HttpRequest,
    interactions: &[HttpInteraction],
    played: &[bool],
    config: &MatchConfig,
    index: Option<&CassetteIndex>,
    allow_played: bool,
) -> Option<usize> {
    let is_match = |idx: usize| {
        interactions
            .get(idx)
            .is_some_and(|interaction| matches_all(request, &interaction.request, config))
    };
    match index {
        Some(index) => pick(
            index.lookup(&request.method, &request.uri).iter().copied(),
            played,
            allow_played,
            is_match,
        ),
        None => pick(0..interactions.len(), played, allow_played, is_match),
    }
}

/// Walk candidates, returning the first unplayed match or, when `allow_played` is set, the first
/// played one.
fn pick<I: Iterator<Item = usize>>(
    candidates: I,
    played: &[bool],
    allow_played: bool,
    mut is_match: impl FnMut(usize) -> bool,
) -> Option<usize> {
    let mut fallback = None;
    for idx in candidates {
        if !is_match(idx) {
            continue;
        }
        if !played.get(idx).copied().unwrap_or(false) {
            return Some(idx);
        }
        if allow_played && fallback.is_none() {
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

/// Index of a gRPC interaction matching `method`, preferring unplayed.
pub fn find_grpc_match_index(
    method: &str,
    interactions: &[GrpcInteraction],
    played: &[bool],
) -> Option<usize> {
    find_grpc_match_index_in(method, interactions, played, true)
}

/// Like [`find_grpc_match_index`], falling back to played interactions only when `allow_played` is set.
pub fn find_grpc_match_index_in(
    method: &str,
    interactions: &[GrpcInteraction],
    played: &[bool],
    allow_played: bool,
) -> Option<usize> {
    pick(0..interactions.len(), played, allow_played, |idx| {
        interactions[idx].request.method == method
    })
}

/// Index of a gRPC interaction matching the method and serialized request body.
/// Prefers unplayed interactions; falls back to an already-played interaction.
pub fn find_grpc_request_match_index(
    request: &GrpcRequest,
    interactions: &[GrpcInteraction],
    played: &[bool],
) -> Option<usize> {
    find_grpc_request_match_index_in(request, interactions, played, true)
}

/// Like [`find_grpc_request_match_index`], falling back to played interactions only when
/// `allow_played` is set.
pub fn find_grpc_request_match_index_in(
    request: &GrpcRequest,
    interactions: &[GrpcInteraction],
    played: &[bool],
    allow_played: bool,
) -> Option<usize> {
    pick(0..interactions.len(), played, allow_played, |idx| {
        let recorded = &interactions[idx].request;
        recorded.method == request.method && recorded.body == request.body
    })
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

/// Index of a WebSocket interaction matching `uri`, preferring unplayed.
pub fn find_ws_match_index(
    uri: &str,
    interactions: &[WsInteraction],
    played: &[bool],
) -> Option<usize> {
    find_ws_match_index_in(uri, interactions, played, true)
}

/// Like [`find_ws_match_index`], falling back to played interactions only when `allow_played` is set.
pub fn find_ws_match_index_in(
    uri: &str,
    interactions: &[WsInteraction],
    played: &[bool],
    allow_played: bool,
) -> Option<usize> {
    pick(0..interactions.len(), played, allow_played, |idx| {
        interactions[idx].uri == uri
    })
}

/// Whether a request satisfies every matcher the config names.
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

    #[test]
    fn test_grpc_request_matching_includes_the_body() {
        use crate::protocol::grpc::{GrpcRequest, GrpcResponse};

        let interaction = GrpcInteraction::new(
            GrpcRequest::new(
                "/demo.Service/Get".to_string(),
                None,
                Some(Body::binary(vec![1])),
            ),
            GrpcResponse::new(0, None, None, None),
            String::new(),
            None,
        );
        let different = GrpcRequest::new(
            "/demo.Service/Get".to_string(),
            None,
            Some(Body::binary(vec![2])),
        );

        assert_eq!(
            find_grpc_request_match_index(&different, &[interaction], &[false]),
            None
        );
    }

    #[test]
    fn replay_only_sessions_fall_back_to_played_interactions() {
        let mut cassette = crate::cassette::Cassette::new();
        cassette.set_interactions(vec![interaction("POST", "/turn")]);
        let config = MatchConfig::default();

        assert_eq!(
            cassette
                .take_match(&request("POST", "/turn"), &config)
                .map(|m| m.0),
            Some(0)
        );
        assert_eq!(
            cassette
                .take_match(&request("POST", "/turn"), &config)
                .map(|m| m.0),
            Some(0)
        );
    }

    #[test]
    fn recording_sessions_replay_only_unplayed_interactions() {
        let mut cassette = crate::cassette::Cassette::new();
        cassette.set_interactions(vec![interaction("POST", "/turn")]);
        cassette.set_recording(true);
        let config = MatchConfig::default();

        assert_eq!(
            cassette
                .take_match(&request("POST", "/turn"), &config)
                .map(|m| m.0),
            Some(0)
        );
        assert!(cassette
            .take_match(&request("POST", "/turn"), &config)
            .is_none());
    }

    #[test]
    fn recording_sessions_count_added_interactions_as_played() {
        use crate::protocol::grpc::{GrpcRequest, GrpcResponse};

        let mut cassette = crate::cassette::Cassette::new();
        cassette.set_recording(true);
        let config = MatchConfig::default();

        cassette.add_interaction(interaction("POST", "/turn"));
        cassette
            .insert_interaction(0, interaction("POST", "/turn"))
            .unwrap();
        assert_eq!(cassette.played_indices, vec![true, true]);
        assert!(cassette
            .take_match(&request("POST", "/turn"), &config)
            .is_none());

        let grpc = GrpcInteraction::new(
            GrpcRequest::new("/pkg.Svc/Call".to_string(), None, None),
            GrpcResponse::new(0, None, None, None),
            String::new(),
            None,
        );
        cassette.add_grpc_interaction(grpc.clone());
        cassette.insert_grpc_interaction(0, grpc.clone()).unwrap();
        assert_eq!(cassette.grpc_played, vec![true, true]);
        assert!(cassette.take_grpc_match("/pkg.Svc/Call").is_none());
        assert!(cassette.take_grpc_request_match(&grpc.request).is_none());

        cassette.add_ws_interaction(WsInteraction::new(
            "wss://example.com".to_string(),
            None,
            None,
            None,
        ));
        assert_eq!(cassette.ws_played, vec![true]);
        assert!(cassette.take_ws_match("wss://example.com").is_none());

        cassette.set_recording(false);
        assert_eq!(
            cassette
                .take_match(&request("POST", "/turn"), &config)
                .map(|m| m.0),
            Some(0)
        );
        assert_eq!(
            cassette.take_grpc_match("/pkg.Svc/Call").map(|m| m.0),
            Some(0)
        );
        assert_eq!(
            cassette.take_ws_match("wss://example.com").map(|m| m.0),
            Some(0)
        );
    }
}
