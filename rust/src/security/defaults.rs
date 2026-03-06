pub static DEFAULT_FILTER_HEADERS: &[&str] = &[
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "proxy-authorization",
    "www-authenticate",
];

pub static DEFAULT_FILTER_QUERY_PARAMS: &[&str] = &[
    "api_key",
    "apikey",
    "token",
    "access_token",
    "client_secret",
];

pub static DEFAULT_BODY_SCRUB_PATTERNS: &[&str] = &[
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
];
