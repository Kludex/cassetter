package cassetter_test

import (
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestResponseHookModifiesLiveAndRecordedResponse(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	var hookCalls atomic.Int64
	transport := cassetter.NewTransport(
		responseTransport("original", 8),
		cassetter.WithPath(path),
		cassetter.WithResponseHook(func(response *http.Response) error {
			hookCalls.Add(1)
			if err := response.Body.Close(); err != nil {
				return err
			}
			response.StatusCode = http.StatusAccepted
			response.Header.Set("X-Hook", "yes")
			response.Body = io.NopCloser(strings.NewReader("modified"))
			response.ContentLength = 8
			return nil
		}),
	)
	response, err := (&http.Client{Transport: transport}).Get("https://example.com/value")
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
	if response.StatusCode != http.StatusAccepted || response.Header.Get("X-Hook") != "yes" || string(body) != "modified" {
		t.Fatalf("response = status %d, headers %v, body %q", response.StatusCode, response.Header, body)
	}
	recorded, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if recorded.Interactions[0].Response.Status != http.StatusAccepted ||
		recorded.Interactions[0].Response.Body.Content != "modified" {
		t.Fatalf("recorded response = %#v", recorded.Interactions[0].Response)
	}
	replay := cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithResponseHook(func(*http.Response) error {
			hookCalls.Add(1)
			return errors.New("response hook ran during replay")
		}),
	)
	replayed, err := (&http.Client{Transport: replay}).Get("https://example.com/value")
	if err != nil {
		t.Fatal(err)
	}
	if err := replayed.Body.Close(); err != nil {
		t.Fatal(err)
	}
	if hookCalls.Load() != 1 {
		t.Fatalf("response hook calls = %d", hookCalls.Load())
	}
}

func TestResponseHookSkipsRecording(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "missing.yaml")
	transport := cassetter.NewTransport(
		responseTransport("live", 4),
		cassetter.WithPath(path),
		cassetter.WithResponseHook(func(*http.Response) error { return cassetter.ErrSkipRecording }),
	)
	response, err := (&http.Client{Transport: transport}).Get("https://example.com/live")
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
	if string(body) != "live" {
		t.Fatalf("response body = %q", body)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("cassette exists after skipped response: %v", err)
	}
	if err := transport.Close(); err != nil {
		t.Fatalf("transport cleanup error = %v", err)
	}
}

func TestTransportRejectsNilBaseResponse(t *testing.T) {
	t.Parallel()
	transport := cassetter.NewTransport(
		roundTripFunc(func(*http.Request) (*http.Response, error) { return nil, nil }),
		cassetter.WithPath(filepath.Join(t.TempDir(), "cassette.yaml")),
	)
	request, err := http.NewRequest(http.MethodGet, "https://example.com", nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transport.RoundTrip(request); err == nil || !strings.Contains(err.Error(), "nil response") {
		t.Fatalf("request error = %v", err)
	}
	if err := transport.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestResponseHookFailureClosesResponseBody(t *testing.T) {
	t.Parallel()
	hookErr := errors.New("response hook failed")
	body := &closeTrackingBody{Reader: strings.NewReader("content")}
	base := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Header: make(http.Header), Body: body, Request: request}, nil
	})
	transport := cassetter.NewTransport(
		base,
		cassetter.WithPath(filepath.Join(t.TempDir(), "cassette.yaml")),
		cassetter.WithResponseHook(func(*http.Response) error { return hookErr }),
	)
	request, err := http.NewRequest(http.MethodGet, "https://example.com", nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transport.RoundTrip(request); !errors.Is(err, hookErr) {
		t.Fatalf("request error = %v", err)
	}
	if !body.closed.Load() {
		t.Fatal("response body was not closed")
	}
}

type closeTrackingBody struct {
	*strings.Reader
	closed atomic.Bool
}

func (body *closeTrackingBody) Close() error {
	body.closed.Store(true)
	return nil
}
