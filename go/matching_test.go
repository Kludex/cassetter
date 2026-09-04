package cassetter_test

import (
	"errors"
	"io"
	"net/http"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestTransportMatchesConfiguredRequestFields(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name        string
		matchers    []cassetter.Matcher
		ignored     []string
		recorded    cassetter.HTTPRequest
		method      string
		uri         string
		headers     http.Header
		body        string
		shouldMatch bool
	}{
		{
			name:        "method",
			matchers:    []cassetter.Matcher{cassetter.MatcherMethod},
			recorded:    cassetter.HTTPRequest{Method: http.MethodPost, URI: "https://example.com/recorded"},
			method:      http.MethodPost,
			uri:         "https://example.com/incoming",
			shouldMatch: true,
		},
		{
			name:        "URI",
			matchers:    []cassetter.Matcher{cassetter.MatcherURI},
			recorded:    cassetter.HTTPRequest{Method: http.MethodPost, URI: "https://example.com/value"},
			method:      http.MethodGet,
			uri:         "https://example.com/value",
			shouldMatch: true,
		},
		{
			name:     "header subset",
			matchers: []cassetter.Matcher{cassetter.MatcherHeaders},
			recorded: cassetter.HTTPRequest{
				Method:  http.MethodGet,
				URI:     "https://example.com/value",
				Headers: http.Header{"x-match": {"one", "two"}},
			},
			method:      http.MethodGet,
			uri:         "https://example.com/other",
			headers:     http.Header{"X-Match": {"one", "two"}, "X-Extra": {"allowed"}},
			shouldMatch: true,
		},
		{
			name:     "text body",
			matchers: []cassetter.Matcher{cassetter.MatcherBody},
			recorded: cassetter.HTTPRequest{
				Method:  http.MethodPost,
				URI:     "https://example.com/value",
				Headers: http.Header{"content-type": {"text/plain"}},
				Body:    cassetter.Body{Type: cassetter.BodyTypeText, Content: "same"},
			},
			method:      http.MethodPost,
			uri:         "https://example.com/other",
			headers:     http.Header{"Content-Type": {"text/plain"}},
			body:        "same",
			shouldMatch: true,
		},
		{
			name:     "ignored JSON paths",
			matchers: []cassetter.Matcher{cassetter.MatcherJSONBody},
			ignored:  []string{"request_id", "data.timestamp", "items[0].nonce"},
			recorded: cassetter.HTTPRequest{
				Method:  http.MethodPost,
				URI:     "https://example.com/value",
				Headers: http.Header{"content-type": {"application/json"}},
				Body: cassetter.Body{Type: cassetter.BodyTypeJSON, Content: map[string]any{
					"request_id": "recorded",
					"data":       map[string]any{"timestamp": "old", "keep": 1},
					"items":      []any{map[string]any{"nonce": "old", "value": 2}},
				}},
			},
			method:  http.MethodPost,
			uri:     "https://example.com/other",
			headers: http.Header{"Content-Type": {"application/json"}},
			body: `{"request_id":"new","data":{"timestamp":"new","keep":1},` +
				`"items":[{"nonce":"new","value":2}]}`,
			shouldMatch: true,
		},
		{
			name:     "different body",
			matchers: []cassetter.Matcher{cassetter.MatcherBody},
			recorded: cassetter.HTTPRequest{
				Method: http.MethodPost,
				URI:    "https://example.com/value",
				Body:   cassetter.Body{Type: cassetter.BodyTypeText, Content: "recorded"},
			},
			method:      http.MethodPost,
			uri:         "https://example.com/value",
			body:        "incoming",
			shouldMatch: false,
		},
	}
	for _, testCase := range tests {
		t.Run(testCase.name, func(t *testing.T) {
			t.Parallel()
			path := filepath.Join(t.TempDir(), "cassette.yaml")
			saveMatchingCassette(t, path, testCase.recorded)
			options := []cassetter.Option{
				cassetter.WithPath(path),
				cassetter.WithRecordMode(cassetter.RecordModeNone),
				cassetter.WithMatchers(testCase.matchers...),
				cassetter.WithIgnoredJSONPaths(testCase.ignored...),
			}
			client := &http.Client{Transport: cassetter.NewTransport(nil, options...)}
			request, err := http.NewRequest(testCase.method, testCase.uri, strings.NewReader(testCase.body))
			if err != nil {
				t.Fatal(err)
			}
			request.Header = testCase.headers.Clone()
			response, err := client.Do(request)
			if !testCase.shouldMatch {
				if !errors.Is(err, cassetter.ErrNoMatch) {
					t.Fatalf("request error = %v", err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			content, err := io.ReadAll(response.Body)
			if err != nil {
				t.Fatal(err)
			}
			if err := response.Body.Close(); err != nil {
				t.Fatal(err)
			}
			if string(content) != "matched" {
				t.Fatalf("response body = %q", content)
			}
		})
	}
}

func saveMatchingCassette(t *testing.T, path string, request cassetter.HTTPRequest) {
	t.Helper()
	cassette := &cassetter.Cassette{
		Version: 1,
		Interactions: []cassetter.HTTPInteraction{{
			Request: request,
			Response: cassetter.HTTPResponse{
				Status: http.StatusOK,
				Body:   cassetter.Body{Type: cassetter.BodyTypeText, Content: "matched"},
			},
		}},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
}
