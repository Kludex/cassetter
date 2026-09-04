pub mod grpc;
pub mod http;
pub mod ws;

/// Maximum container nesting accepted for a JSON payload.
///
/// Bindings that convert host-language values into `serde_json::Value` must
/// enforce this: the converters recurse once per level with no limit of their
/// own, so a deeply nested argument would overflow the Rust stack and abort
/// the process instead of raising.
pub const MAX_JSON_DEPTH: usize = 256;
