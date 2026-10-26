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
    if let (Normalized::Json(recorded), Normalized::Json(live)) = (&expected.body, &actual.body) {
        actual.body = Normalized::Json(tolerate(recorded, live, compare.float_tolerance));
    }
    let (expected, actual) = (render(expected), render(actual));
    (expected != actual).then(|| unified_diff(&expected, &actual))
}

struct Response {
    status: u16,
    headers: Vec<(String, String)>,
    body_type: &'static str,
    body: Normalized,
}

enum Normalized {
    Json(Value),
    Text(String),
    Binary(Vec<u8>),
    None,
}

fn normalize(compare: &Compare, response: &HttpResponse) -> Response {
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
    headers.sort_by(|a, b| (a.0.to_ascii_lowercase(), &a.0).cmp(&(b.0.to_ascii_lowercase(), &b.0)));
    headers
        .iter_mut()
        .for_each(|(name, _)| name.make_ascii_lowercase());
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
    Response {
        status: response.status,
        headers,
        body_type: response.body.inner.type_name(),
        body,
    }
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
                .map(|(index, item)| {
                    let path = format!("{current}[{index}]");
                    if paths.contains(&path) {
                        Value::Null
                    } else {
                        drop_paths(item, paths, &path)
                    }
                })
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
        (Value::Number(a), Value::Number(b)) => {
            let difference = match (integer(a), integer(b)) {
                (Some(a), Some(b)) => Some(a.abs_diff(b) as f64),
                _ => a.as_f64().zip(b.as_f64()).map(|(a, b)| (a - b).abs()),
            };
            match difference {
                Some(difference) if difference <= tolerance => recorded.clone(),
                _ => live.clone(),
            }
        }
        _ => live.clone(),
    }
}

fn integer(number: &serde_json::Number) -> Option<i128> {
    number
        .as_i64()
        .map(i128::from)
        .or_else(|| number.as_u64().map(i128::from))
}

fn render(response: Response) -> Vec<String> {
    let Response {
        status,
        headers,
        body_type,
        mut body,
    } = response;
    let mut lines = vec![format!("status: {status}"), "@@ headers @@".to_string()];
    lines.extend(
        headers
            .iter()
            .map(|(name, value)| format!("{name}: {value}")),
    );
    lines.push(format!("@@ {body_type} body @@"));
    match &mut body {
        Normalized::Json(value) => {
            sort_keys(value);
            let pretty = serde_json::to_string_pretty(value).unwrap_or_default();
            lines.extend(pretty.lines().map(str::to_string));
        }
        Normalized::Text(text) => lines.extend(text.split('\n').map(str::to_string)),
        Normalized::Binary(bytes) => lines.push(format!("b'{}'", bytes.escape_ascii())),
        Normalized::None => lines.push("null".to_string()),
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

const CONTEXT: usize = 3;
const MAX_LCS_CELLS: usize = 1 << 22;

/// A unified diff in the format of Python's `difflib.unified_diff`, with 3 lines of context.
fn unified_diff(expected: &[String], actual: &[String]) -> String {
    let ops = edit_script(expected, actual);
    let mut groups: Vec<(usize, usize)> = Vec::new();
    for (index, _) in ops.iter().enumerate().filter(|(_, op)| op.tag != ' ') {
        match groups.last_mut() {
            Some((_, end)) if index - *end <= 2 * CONTEXT => *end = index + 1,
            _ => groups.push((index, index + 1)),
        }
    }
    let mut out = vec!["--- recorded".to_string(), "+++ live".to_string()];
    for (start, end) in groups {
        let hunk = &ops[start.saturating_sub(CONTEXT)..(end + CONTEXT).min(ops.len())];
        let old = hunk.iter().filter(|op| op.tag != '+').count();
        let new = hunk.iter().filter(|op| op.tag != '-').count();
        out.push(format!(
            "@@ -{} +{} @@",
            range(hunk[0].old, old),
            range(hunk[0].new, new)
        ));
        out.extend(hunk.iter().map(|op| format!("{}{}", op.tag, op.line)));
    }
    out.join("\n")
}

fn range(start: usize, length: usize) -> String {
    match length {
        0 => format!("{start},0"),
        1 => format!("{}", start + 1),
        _ => format!("{},{length}", start + 1),
    }
}

struct Op<'a> {
    tag: char,
    line: &'a str,
    old: usize,
    new: usize,
}

/// The common prefix and suffix are kept; the middle is diffed by LCS, or replaced wholesale when too large.
fn edit_script<'a>(expected: &'a [String], actual: &'a [String]) -> Vec<Op<'a>> {
    let prefix = expected
        .iter()
        .zip(actual)
        .take_while(|(a, b)| a == b)
        .count();
    let suffix = expected[prefix..]
        .iter()
        .rev()
        .zip(actual[prefix..].iter().rev())
        .take_while(|(a, b)| a == b)
        .count();
    let (a, b) = (
        &expected[prefix..expected.len() - suffix],
        &actual[prefix..actual.len() - suffix],
    );
    let (n, m) = (a.len(), b.len());
    let mut tags = Vec::with_capacity(n + m);
    if n * m <= MAX_LCS_CELLS {
        let mut lcs = vec![0u32; (n + 1) * (m + 1)];
        let at = |i: usize, j: usize| i * (m + 1) + j;
        for i in (0..n).rev() {
            for j in (0..m).rev() {
                lcs[at(i, j)] = if a[i] == b[j] {
                    lcs[at(i + 1, j + 1)] + 1
                } else {
                    lcs[at(i + 1, j)].max(lcs[at(i, j + 1)])
                };
            }
        }
        let (mut i, mut j) = (0, 0);
        while i < n || j < m {
            if i < n && j < m && a[i] == b[j] {
                tags.push(' ');
                (i, j) = (i + 1, j + 1);
            } else if j == m || (i < n && lcs[at(i + 1, j)] >= lcs[at(i, j + 1)]) {
                tags.push('-');
                i += 1;
            } else {
                tags.push('+');
                j += 1;
            }
        }
    } else {
        tags.extend(std::iter::repeat_n('-', n).chain(std::iter::repeat_n('+', m)));
    }
    let tags = std::iter::repeat_n(' ', prefix)
        .chain(tags)
        .chain(std::iter::repeat_n(' ', suffix));
    let (mut old, mut new) = (0, 0);
    tags.map(|tag| {
        let op = Op {
            tag,
            line: if tag == '+' {
                &actual[new]
            } else {
                &expected[old]
            },
            old,
            new,
        };
        old += usize::from(tag != '+');
        new += usize::from(tag != '-');
        op
    })
    .collect()
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{glob, tolerate, unified_diff};

    #[test]
    fn tolerance_compares_integers_exactly() {
        let recorded = json!([9007199254740992u64, 1, 0.3]);
        let live = json!([9007199254740993u64, 2, 0.30000000000000004]);
        assert_eq!(
            tolerate(&recorded, &live, 1e-9),
            json!([9007199254740993u64, 2, 0.3])
        );
        assert_eq!(tolerate(&recorded, &live, 1.0), recorded);
    }

    fn lines(text: &str) -> Vec<String> {
        text.split('\n').map(str::to_string).collect()
    }

    #[test]
    fn unified_diff_matches_difflib_hunks() {
        let expected = lines("a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk\nl\nm\nn");
        let mut actual = expected.clone();
        actual[1] = "B".to_string();
        actual.remove(12);
        assert_eq!(
            unified_diff(&expected, &actual),
            "--- recorded\n+++ live\n@@ -1,5 +1,5 @@\n a\n-b\n+B\n c\n d\n e\n@@ -10,5 +10,4 @@\n j\n k\n l\n-m\n n"
        );
        assert_eq!(
            unified_diff(&lines("a"), &lines("")),
            "--- recorded\n+++ live\n@@ -1 +1 @@\n-a\n+"
        );
    }

    #[test]
    fn unified_diff_replaces_large_mismatches_without_a_quadratic_table() {
        let expected: Vec<String> = (0..5000).map(|i| format!("a{i}")).collect();
        let actual: Vec<String> = (0..5000).map(|i| format!("b{i}")).collect();
        let diff = unified_diff(&expected, &actual);
        assert!(diff.starts_with("--- recorded\n+++ live\n@@ -1,5000 +1,5000 @@\n-a0\n"));
        assert_eq!(diff.lines().count(), 3 + 10000);
    }

    #[test]
    fn glob_matches_like_fnmatch() {
        assert!(glob(b"x-price-*", b"x-price-estimate"));
        assert!(glob(b"x-price-*", b"x-price-"));
        assert!(!glob(b"x-price-*", b"x-cost"));
        assert!(glob(b"content-?ype", b"content-type"));
        assert!(!glob(b"content-type", b"content-types"));
    }
}
