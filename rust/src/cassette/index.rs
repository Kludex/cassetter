use std::collections::HashMap;

/// A simple index for fast cassette lookups by method + URI.
pub struct CassetteIndex {
    /// Maps "METHOD URI" -> list of interaction indices.
    entries: HashMap<String, Vec<usize>>,
}

impl CassetteIndex {
    pub fn new() -> Self {
        CassetteIndex {
            entries: HashMap::new(),
        }
    }

    /// Build an index from a list of interactions.
    pub fn build(interactions: &[crate::protocol::http::HttpInteraction]) -> Self {
        let mut index = CassetteIndex::new();
        for (i, interaction) in interactions.iter().enumerate() {
            let key = format!(
                "{} {}",
                interaction.request.method.to_uppercase(),
                interaction.request.uri
            );
            index.entries.entry(key).or_default().push(i);
        }
        index
    }

    /// Lookup candidate indices for a given method + URI.
    pub fn lookup(&self, method: &str, uri: &str) -> Vec<usize> {
        let key = format!("{} {uri}", method.to_uppercase());
        self.entries.get(&key).cloned().unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::http::*;

    fn make_interaction(method: &str, uri: &str) -> HttpInteraction {
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

    #[test]
    fn test_index_lookup() {
        let interactions = vec![
            make_interaction("GET", "https://api.example.com/users"),
            make_interaction("POST", "https://api.example.com/users"),
            make_interaction("GET", "https://api.example.com/users"),
        ];
        let index = CassetteIndex::build(&interactions);

        assert_eq!(
            index.lookup("GET", "https://api.example.com/users"),
            vec![0, 2]
        );
        assert_eq!(
            index.lookup("POST", "https://api.example.com/users"),
            vec![1]
        );
        assert!(index
            .lookup("DELETE", "https://api.example.com/users")
            .is_empty());
    }
}
