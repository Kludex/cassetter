package cassetter_test

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestTransportPrefersUnusedThenRepeatsFirstMatch(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	uri := "https://example.com/value"
	cassette := &cassetter.Cassette{Version: 1}
	for _, value := range []string{"one", "two"} {
		cassette.Interactions = append(cassette.Interactions, cassetter.HTTPInteraction{
			Request: cassetter.HTTPRequest{Method: http.MethodGet, URI: uri},
			Response: cassetter.HTTPResponse{
				Status: http.StatusOK,
				Body:   cassetter.Body{Type: cassetter.BodyTypeText, Content: value},
			},
		})
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Transport: cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)}
	for index, expected := range []string{"one", "two", "one"} {
		response, err := client.Get(uri)
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
		if string(content) != expected {
			t.Fatalf("response %d = %q", index, content)
		}
	}
}

func TestTransportNormalizesURIsForMatching(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	saveMatchingCassette(t, path, cassetter.HTTPRequest{
		Method: http.MethodGet,
		URI:    "https://us.example.com/accounts/123",
	})
	normalize := func(value string) string {
		parsed, err := url.Parse(value)
		if err != nil {
			return value
		}
		parsed.Host = "api.example.com"
		parsed.Path = "/accounts/{account_id}"
		return parsed.String()
	}
	client := &http.Client{Transport: cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithURINormalizer(normalize),
	)}
	response, err := client.Get("https://eu.example.com/accounts/999")
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestTransportMatchesBodyWithoutGetBody(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	saveMatchingCassette(t, path, cassetter.HTTPRequest{
		Method:  http.MethodPost,
		URI:     "https://example.com/value",
		Headers: http.Header{"content-type": {"text/plain"}},
		Body:    cassetter.Body{Type: cassetter.BodyTypeText, Content: "streamed"},
	})
	client := &http.Client{Transport: cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithMatchers(cassetter.MatcherMethod, cassetter.MatcherURI, cassetter.MatcherBody),
	)}
	request, err := http.NewRequest(
		http.MethodPost,
		"https://example.com/value",
		io.NopCloser(strings.NewReader("streamed")),
	)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "text/plain")
	if request.GetBody != nil {
		t.Fatal("request unexpectedly has GetBody")
	}
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestTransportRejectsInvalidMatchers(t *testing.T) {
	t.Parallel()
	tests := map[string][]cassetter.Matcher{
		"empty":   {},
		"unknown": {cassetter.Matcher("unknown")},
	}
	for name, matchers := range tests {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			transport := cassetter.NewTransport(
				nil,
				cassetter.WithPath(filepath.Join(t.TempDir(), "cassette.yaml")),
				cassetter.WithMatchers(matchers...),
			)
			if err := transport.Initialize(); err == nil {
				t.Fatal("Initialize accepted invalid request matchers")
			}
		})
	}
}

func TestTransportHeaderMatchDoesNotReadBody(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	saveMatchingCassette(t, path, cassetter.HTTPRequest{
		Method:  http.MethodGet,
		URI:     "https://recorded.example.com/value",
		Headers: http.Header{"x-match": {"yes"}},
	})
	client := &http.Client{Transport: cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithMatchers(cassetter.MatcherHeaders),
	)}
	request, err := http.NewRequest(http.MethodPost, "https://example.com/value", failingReadCloser{})
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("X-Match", "yes")
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestTransportJSONBodyMatcherDistinguishesLargeNumbers(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	saveMatchingCassette(t, path, cassetter.HTTPRequest{
		Method: http.MethodPost,
		URI:    "https://example.com/value",
		Body: cassetter.Body{Type: cassetter.BodyTypeJSON, Content: map[string]any{
			"id": json.Number("18446744073709551616"),
		}},
	})
	client := &http.Client{Transport: cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithMatchers(cassetter.MatcherJSONBody),
	)}
	request, err := http.NewRequest(
		http.MethodPost,
		"https://example.com/value",
		strings.NewReader(`{"id":18446744073709551617}`),
	)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/json")
	if _, err := client.Do(request); !errors.Is(err, cassetter.ErrNoMatch) {
		t.Fatalf("request error = %v", err)
	}
}

func TestTransportBodyMatchReadFailure(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	saveMatchingCassette(t, path, cassetter.HTTPRequest{
		Method: http.MethodPost,
		URI:    "https://example.com/value",
	})
	client := &http.Client{Transport: cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithMatchers(cassetter.MatcherBody),
	)}
	request, err := http.NewRequest(http.MethodPost, "https://example.com/value", failingReadCloser{})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.Do(request); err == nil || errors.Is(err, cassetter.ErrNoMatch) {
		t.Fatalf("request error = %v", err)
	}
}

type failingReadCloser struct{}

func (failingReadCloser) Read([]byte) (int, error) {
	return 0, errors.New("read failed")
}

func (failingReadCloser) Close() error {
	return nil
}
