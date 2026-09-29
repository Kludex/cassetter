package cassetter

import (
	"net/http"
	"net/url"
	"strings"
)

var defaultFilterHeaders = []string{
	"authorization", "cookie", "set-cookie", "x-api-key", "api-key", "x-auth-token",
	"proxy-authorization", "www-authenticate", "x-goog-api-key", "x-amz-security-token",
}

var defaultFilterQueryParameters = []string{
	"api_key", "apikey", "token", "access_token", "client_secret",
}

var defaultBodyScrubPatterns = []string{
	"access_token", "refresh_token", "client_secret", "password",
}

// SecurityConfig controls write-time secret filtering.
type SecurityConfig struct {
	FilterHeaders         []string
	FilterQueryParameters []string
	BodyScrubPatterns     []string
	Replacement           string
}

// DefaultSecurityConfig returns the safe defaults shared with cassetter.
func DefaultSecurityConfig() SecurityConfig {
	return SecurityConfig{
		FilterHeaders:         append([]string(nil), defaultFilterHeaders...),
		FilterQueryParameters: append([]string(nil), defaultFilterQueryParameters...),
		BodyScrubPatterns:     append([]string(nil), defaultBodyScrubPatterns...),
		Replacement:           "[FILTERED]",
	}
}

// filterHeaders removes filtered headers, ignoring case. An entry may use `*` to match any run of
// characters, and an entry starting with `!` keeps the headers it matches even when another entry, including
// a default, would remove them.
func filterHeaders(headers http.Header, filtered []string) {
	var kept, removed []string
	for _, entry := range filtered {
		entry = strings.ToLower(entry)
		if pattern, ok := strings.CutPrefix(entry, "!"); ok {
			kept = append(kept, pattern)
		} else {
			removed = append(removed, entry)
		}
	}
	for name := range headers {
		lower := strings.ToLower(name)
		if matchesAny(removed, lower) && !matchesAny(kept, lower) {
			delete(headers, name)
		}
	}
}

func matchesAny(patterns []string, name string) bool {
	for _, pattern := range patterns {
		if globMatch(pattern, name) {
			return true
		}
	}
	return false
}

// globMatch reports whether name matches pattern, where `*` matches any run of characters.
func globMatch(pattern, name string) bool {
	parts := strings.Split(pattern, "*")
	rest, ok := strings.CutPrefix(name, parts[0])
	if !ok {
		return false
	}
	if len(parts) == 1 {
		return rest == ""
	}
	for _, part := range parts[1 : len(parts)-1] {
		index := strings.Index(rest, part)
		if index < 0 {
			return false
		}
		rest = rest[index+len(part):]
	}
	last := parts[len(parts)-1]
	return len(rest) >= len(last) && strings.HasSuffix(rest, last)
}

func scrubURI(uri string, filtered []string, replacement string) string {
	parsed, err := url.Parse(uri)
	if err == nil && parsed.User != nil {
		parsed.User = nil
		uri = parsed.String()
	}
	queryStart := strings.IndexByte(uri, '?')
	fragmentStart := strings.IndexByte(uri, '#')
	if fragmentStart >= 0 && queryStart > fragmentStart {
		queryStart = -1
	}
	if queryStart < 0 && fragmentStart < 0 {
		return uri
	}
	baseEnd := len(uri)
	if queryStart >= 0 {
		baseEnd = queryStart
	} else if fragmentStart >= 0 {
		baseEnd = fragmentStart
	}
	var result strings.Builder
	result.WriteString(uri[:baseEnd])
	if queryStart >= 0 {
		end := len(uri)
		if fragmentStart >= 0 {
			end = fragmentStart
		}
		result.WriteByte('?')
		result.WriteString(scrubPairs(uri[queryStart+1:end], filtered, replacement))
	}
	if fragmentStart >= 0 {
		result.WriteByte('#')
		result.WriteString(scrubPairs(uri[fragmentStart+1:], filtered, replacement))
	}
	return result.String()
}

func scrubPairs(value string, filtered []string, replacement string) string {
	pairs := strings.Split(value, "&")
	for index, pair := range pairs {
		key, _, found := strings.Cut(pair, "=")
		if !found {
			continue
		}
		decoded, err := url.QueryUnescape(key)
		if err != nil {
			decoded = key
		}
		for _, candidate := range filtered {
			if strings.EqualFold(decoded, candidate) {
				pairs[index] = key + "=" + replacement
				break
			}
		}
	}
	return strings.Join(pairs, "&")
}
