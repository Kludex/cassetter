pub static DEFAULT_FILTER_HEADERS: &[&str] = &[
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "proxy-authorization",
    "www-authenticate",
    // Provider-specific, and as much a credential as `x-api-key`: the Google
    // SDKs put the API key here, and SigV4 puts temporary STS credentials here.
    "x-goog-api-key",
    "x-amz-security-token",
];

pub static DEFAULT_FILTER_QUERY_PARAMS: &[&str] = &[
    "api_key",
    "apikey",
    "token",
    "access_token",
    "client_secret",
    "x-amz-credential",
    "x-amz-signature",
    "x-amz-security-token",
];

pub static DEFAULT_BODY_SCRUB_PATTERNS: &[&str] = &[
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "api_key",
    "api-key",
];
