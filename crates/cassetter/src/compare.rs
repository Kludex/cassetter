//! What [`RecordMode::Verify`](crate::RecordMode::Verify) compares between a recorded and a live response.

use std::fmt;
use std::sync::Arc;

use cassetter_core::protocol::http::{BodyContent, HttpResponse};
use serde_json::{Map, Value};

/// What verify mode compares. The status is always compared; everything not listed here is ignored.
#[derive(Clone, Debug, Default)]
pub struct Compare {
    /// Response header names to compare by value. Globs such as `x-price-*` are allowed.
    pub headers: Vec<String>,
    /// Paths removed from JSON bodies before comparing, in the `ignore_json_paths` syntax
    /// (`id`, `data.created`, `items[0].id`). With `sse`, they apply to each event's payload.
    pub json_ignore: Vec<String>,
    /// Compare the body as a list of Server-Sent Events `data:` payloads, so chunk boundaries do not matter.
    pub sse: bool,
    /// Largest absolute difference between two JSON numbers that still counts as equal.
    pub float_tolerance: f64,
}

type Hook = dyn Fn(HttpResponse, HttpResponse) -> (HttpResponse, HttpResponse) + Send + Sync;

#[derive(Clone)]
pub(crate) struct BeforeCompareResponse(pub(crate) Arc<Hook>);

impl fmt::Debug for BeforeCompareResponse {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("BeforeCompareResponse")
    }
}

/// A unified diff of the rendered responses when `live` is not equivalent to `recorded`.
pub(crate) fn diff_responses(
    compare: &Compare,
    recorded: &HttpResponse,
    live: &HttpResponse,
) -> Option<String> {
    let expected = normalize(compare, recorded);
    let mut actual = normalize(compare, live);
    if let (Normalized::Json(recorded), Normalized::Json(live)) = (&expected.2, &actual.2) {
        actual.2 = Normalized::Json(tolerate(recorded, live, compare.float_tolerance));
    }
    let (expected, actual) = (render(expected), render(actual));
    (expected != actual).then(|| unified_diff(&expected, &actual))
}

enum Normalized {
    Json(Value),
    Text(String),
    Binary(Vec<u8>),
    None,
}

fn normalize(
    compare: &Compare,
    response: &HttpResponse,
) -> (u16, Vec<(String, String)>, Normalized) {
    let mut headers: Vec<(String, String)> = response
        .headers
        .iter()
        .filter(|(name, _)| {
            compare.headers.iter().any(|pattern| {
                glob(
                    pattern.to_ascii_lowercase().as_bytes(),
                    name.to_ascii_lowercase().as_bytes(),
                )
            })
        })
        .flat_map(|(name, values)| {
            values
                .iter()
                .map(move |value| (name.clone(), value.clone()))
        })
        .collect();
    headers.sort_by(|a, b| a.0.cmp(&b.0));
    let body = match &response.body.inner {
        BodyContent::Json(value) => Normalized::Json(drop_paths(value, &compare.json_ignore, "")),
        BodyContent::Text(text) if compare.sse => Normalized::Json(Value::Array(
            sse_events(text)
                .iter()
                .map(|event| drop_paths(event, &compare.json_ignore, ""))
                .collect(),
        )),
        BodyContent::Text(text) => Normalized::Text(text.clone()),
        BodyContent::Binary(bytes) => Normalized::Binary(bytes.clone()),
        BodyContent::None => Normalized::None,
    };
    (response.status, headers, body)
}

fn sse_events(text: &str) -> Vec<Value> {
    text.replace("\r\n", "\n")
        .split("\n\n")
        .filter_map(|block| {
            let lines: Vec<&str> = block
                .split('\n')
                .filter_map(|line| line.strip_prefix("data:"))
                .map(|line| line.strip_prefix(' ').unwrap_or(line))
                .collect();
            if lines.is_empty() {
                return None;
            }
            let data = lines.join("\n");
            Some(serde_json::from_str(&data).unwrap_or(Value::String(data)))
        })
        .collect()
}

fn drop_paths(value: &Value, paths: &[String], current: &str) -> Value {
    match value {
        Value::Object(object) => Value::Object(
            object
                .iter()
                .filter_map(|(key, item)| {
                    let path = if current.is_empty() {
                        key.clone()
                    } else {
                        format!("{current}.{key}")
                    };
                    (!paths.contains(&path)).then(|| (key.clone(), drop_paths(item, paths, &path)))
                })
                .collect(),
        ),
        Value::Array(items) => Value::Array(
            items
                .iter()
                .enumerate()
                .map(|(index, item)| drop_paths(item, paths, &format!("{current}[{index}]")))
                .collect(),
        ),
        _ => value.clone(),
    }
}

/// `live` with numbers within `tolerance` of their recording replaced by it, so they drop out of the diff.
fn tolerate(recorded: &Value, live: &Value, tolerance: f64) -> Value {
    match (recorded, live) {
        (Value::Object(recorded), Value::Object(live)) => Value::Object(
            live.iter()
                .map(|(key, value)| {
                    let value = match recorded.get(key) {
                        Some(recorded) => tolerate(recorded, value, tolerance),
                        None => value.clone(),
                    };
                    (key.clone(), value)
                })
                .collect(),
        ),
        (Value::Array(recorded), Value::Array(live)) => Value::Array(
            live.iter()
                .enumerate()
                .map(|(index, value)| match recorded.get(index) {
                    Some(recorded) => tolerate(recorded, value, tolerance),
                    None => value.clone(),
                })
                .collect(),
        ),
        (Value::Number(a), Value::Number(b)) => match (a.as_f64(), b.as_f64()) {
            (Some(a), Some(b)) if (a - b).abs() <= tolerance => recorded.clone(),
            _ => live.clone(),
        },
        _ => live.clone(),
    }
}

fn render((status, headers, mut body): (u16, Vec<(String, String)>, Normalized)) -> Vec<String> {
    let mut lines = vec![format!("status: {status}"), "@@ headers @@".to_string()];
    lines.extend(
        headers
            .iter()
            .map(|(name, value)| format!("{name}: {value}")),
    );
    lines.push("@@ body @@".to_string());
    match &mut body {
        Normalized::Json(value) => {
            sort_keys(value);
            let pretty = serde_json::to_string_pretty(value).unwrap_or_default();
            lines.extend(pretty.lines().map(str::to_string));
        }
        Normalized::Text(text) => lines.extend(text.lines().map(str::to_string)),
        Normalized::Binary(bytes) => lines.push(bytes.escape_ascii().to_string()),
        Normalized::None => {}
    }
    lines
}

fn sort_keys(value: &mut Value) {
    match value {
        Value::Object(object) => {
            let mut entries: Vec<(String, Value)> = std::mem::take(object).into_iter().collect();
            entries.sort_by(|a, b| a.0.cmp(&b.0));
            for (_, item) in &mut entries {
                sort_keys(item);
            }
            *object = entries.into_iter().collect::<Map<_, _>>();
        }
        Value::Array(items) => items.iter_mut().for_each(sort_keys),
        _ => {}
    }
}

/// `fnmatch`-style matching of `*` and `?`.
fn glob(pattern: &[u8], text: &[u8]) -> bool {
    match (pattern.split_first(), text.split_first()) {
        (None, _) => text.is_empty(),
        (Some((b'*', rest)), _) => (0..=text.len()).any(|index| glob(rest, &text[index..])),
        (Some((&expected, rest)), Some((&found, tail))) => {
            (expected == b'?' || expected == found) && glob(rest, tail)
        }
        (Some(_), None) => false,
    }
}

// shortcut: whole-file diff without hunk headers or trimmed context, add hunks if large bodies make it unreadable.
fn unified_diff(expected: &[String], actual: &[String]) -> String {
    let (n, m) = (expected.len(), actual.len());
    let mut lcs = vec![vec![0usize; m + 1]; n + 1];
    for i in (0..n).rev() {
        for j in (0..m).rev() {
            lcs[i][j] = if expected[i] == actual[j] {
                lcs[i + 1][j + 1] + 1
            } else {
                lcs[i + 1][j].max(lcs[i][j + 1])
            };
        }
    }
    let mut out = vec!["--- recorded".to_string(), "+++ live".to_string()];
    let (mut i, mut j) = (0, 0);
    while i < n || j < m {
        if i < n && j < m && expected[i] == actual[j] {
            out.push(format!(" {}", expected[i]));
            (i, j) = (i + 1, j + 1);
        } else if j == m || (i < n && lcs[i + 1][j] >= lcs[i][j + 1]) {
            out.push(format!("-{}", expected[i]));
            i += 1;
        } else {
            out.push(format!("+{}", actual[j]));
            j += 1;
        }
    }
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::glob;

    #[test]
    fn glob_matches_like_fnmatch() {
        assert!(glob(b"x-price-*", b"x-price-estimate"));
        assert!(glob(b"x-price-*", b"x-price-"));
        assert!(!glob(b"x-price-*", b"x-cost"));
        assert!(glob(b"content-?ype", b"content-type"));
        assert!(!glob(b"content-type", b"content-types"));
    }
}
