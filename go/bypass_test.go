package cassetter_test

import (
	"errors"
	"io"
	"net/http"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestTransportBypassesLocalhost(t *testing.T) {
	t.Parallel()
	for _, uri := range []string{
		"http://localhost:8080/health",
		"http://127.0.0.1/health",
		"http://[::1]:8080/health",
	} {
		uri := uri
		t.Run(uri, func(t *testing.T) {
			t.Parallel()
			var calls atomic.Int64
			base := roundTripFunc(func(request *http.Request) (*http.Response, error) {
				calls.Add(1)
				return &http.Response{
					StatusCode:    http.StatusOK,
					Header:        make(http.Header),
					Body:          io.NopCloser(strings.NewReader("live")),
					ContentLength: 4,
					Request:       request,
				}, nil
			})
			transport := cassetter.NewTransport(
				base,
				cassetter.WithPath(filepath.Join(t.TempDir(), "missing.yaml")),
				cassetter.WithRecordMode(cassetter.RecordModeNone),
				cassetter.WithIgnoreLocalhost(),
				cassetter.WithRequestHook(func(*http.Request) error {
					return errors.New("request hook ran for bypassed request")
				}),
				cassetter.WithResponseHook(func(*http.Response) error {
					return errors.New("response hook ran for bypassed request")
				}),
			)
			response, err := (&http.Client{Transport: transport}).Get(uri)
			if err != nil {
				t.Fatal(err)
			}
			body, err := io.ReadAll(response.Body)
			if err != nil {
				t.Fatal(err)
			}
			if err := response.Body.Close(); err != nil {
				t.Fatal(err)
			}
			if string(body) != "live" || calls.Load() != 1 {
				t.Fatalf("body = %q, calls = %d", body, calls.Load())
			}
		})
	}
}

func TestTransportBypassesMatchingHosts(t *testing.T) {
	t.Parallel()
	var calls atomic.Int64
	base := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		calls.Add(1)
		return &http.Response{
			StatusCode: http.StatusNoContent,
			Header:     make(http.Header),
			Body:       http.NoBody,
			Request:    request,
		}, nil
	})
	transport := cassetter.NewTransport(
		base,
		cassetter.WithPath(filepath.Join(t.TempDir(), "missing.yaml")),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithIgnoreHosts("*.googleapis.com", "accounts.example.com"),
	)
	client := &http.Client{Transport: transport}
	for _, uri := range []string{"https://oauth2.googleapis.com/token", "https://accounts.example.com/login"} {
		response, err := client.Get(uri)
		if err != nil {
			t.Fatal(err)
		}
		if err := response.Body.Close(); err != nil {
			t.Fatal(err)
		}
	}
	if calls.Load() != 2 {
		t.Fatalf("base transport calls = %d", calls.Load())
	}
	if _, err := client.Get("https://api.example.com/data"); !errors.Is(err, cassetter.ErrNoMatch) {
		t.Fatalf("nonmatching host error = %v", err)
	}
}

func TestTransportValidatesIgnoredHostPatterns(t *testing.T) {
	t.Parallel()
	transport := cassetter.NewTransport(
		nil,
		cassetter.WithPath(filepath.Join(t.TempDir(), "cassette.yaml")),
		cassetter.WithIgnoreHosts("[invalid"),
	)
	if err := transport.Initialize(); err == nil || !strings.Contains(err.Error(), "invalid ignored host pattern") {
		t.Fatalf("initialization error = %v", err)
	}
}

func TestClosedTransportRejectsBypassedRequests(t *testing.T) {
	t.Parallel()
	var calls atomic.Int64
	transport := cassetter.NewTransport(
		roundTripFunc(func(*http.Request) (*http.Response, error) {
			calls.Add(1)
			return nil, errors.New("unexpected request")
		}),
		cassetter.WithPath(filepath.Join(t.TempDir(), "cassette.yaml")),
		cassetter.WithIgnoreLocalhost(),
	)
	if err := transport.Close(); err != nil {
		t.Fatal(err)
	}
	request, err := http.NewRequest(http.MethodGet, "http://localhost/health", nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transport.RoundTrip(request); !errors.Is(err, cassetter.ErrTransportClosed) {
		t.Fatalf("request error = %v", err)
	}
	if calls.Load() != 0 {
		t.Fatalf("base transport calls = %d", calls.Load())
	}
}
