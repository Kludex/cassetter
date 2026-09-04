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

// Scrub applies write-time secret filtering to every HTTP interaction.
func (c *Cassette) Scrub(config SecurityConfig) {
	for index := range c.Interactions {
		interaction := &c.Interactions[index]
		filterHeaders(interaction.Request.Headers, config.FilterHeaders)
		filterHeaders(interaction.Response.Headers, config.FilterHeaders)
		interaction.Request.URI = scrubURI(
			interaction.Request.URI,
			config.FilterQueryParameters,
			config.Replacement,
		)
		interaction.Request.Body = scrubBody(
			interaction.Request.Body,
			config.BodyScrubPatterns,
			config.Replacement,
		)
		interaction.Response.Body = scrubBody(
			interaction.Response.Body,
			config.BodyScrubPatterns,
			config.Replacement,
		)
		retagContentLength(interaction.Request.Headers, interaction.Request.Body)
		retagContentLength(interaction.Response.Headers, interaction.Response.Body)
	}
}

func filterHeaders(headers http.Header, filtered []string) {
	for name := range headers {
		for _, candidate := range filtered {
			if strings.EqualFold(name, candidate) {
				delete(headers, name)
				break
			}
		}
	}
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
